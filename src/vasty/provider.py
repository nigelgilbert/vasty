"""The adapter boundary between vasty and Vast.ai.

Every `vastai` import and call lives in this file. Code above it uses the
`Provider` protocol and the normalized rows in `vasty.models`. `VastProvider`
imports `vastai` lazily inside its methods so stdlib-only commands stay fast.

`import vastai` measured 160-175ms warm on vastai 1.9.1 and Python 3.14, so
the adapter uses the SDK's `VastClient` and its retry logic. Importing any
`vastai` submodule runs the package `__init__`, so no narrower import is cheaper.

Endpoints and the fields read from each response:

- Search: SDK `offers.search_offers` (`POST /bundles/`). Reads `offers[]`:
  `id`, `gpu_name`, `num_gpus`, `gpu_ram` (MB), `dph_total`, `reliability`
  (else `reliability2`), `inet_down`, `direct_port_count`, `geolocation`.
- Create: SDK `instances.create_instance_from_payload` (`PUT /asks/{id}/`)
  on a client with one attempt. Reads `success`, `new_contract`, `msg`, `error`.
- List: SDK `instances.show_instances_v1` (`GET /api/v1/instances/`), paged
  by passing each `next_token` back as `after_token`. Reads `instances[]`
  and `next_token`.
- Get: `GET /instances/{id}/?owner=me`. Reads `instances` as one row.
- Instance rows: `id`, `label`, `actual_status`, `gpu_name`, `num_gpus`,
  `gpu_ram` (MB), `dph_total`, `public_ipaddr`, `ssh_host`, `ssh_port`,
  `ports` (Docker-style map), `image_uuid`, `image_runtype`.
- Destroy and label: SDK `instances.destroy_instance` and `label_instance`.
- Charges: SDK `billing.show_invoices_v1(charges=True)` (`GET /charges/`)
  filtered to instance charges and paged by `next_token`. Reads top-level
  `results[]`: `source` (instance id, bare or `instance-<id>`), `metadata.instance_id`
  as a fallback, `amount`, `start` and `end`.
- Balance: SDK `billing.show_user` (`GET /users/current`). Reads `balance`
  and `credit`.
- SSH keys: SDK `keys.show_ssh_keys` (`GET /ssh/`), `keys.create_ssh_key`
  (`POST /ssh/`) and `keys.attach_ssh` (`POST /instances/{id}/ssh/`).
"""

from __future__ import annotations

import json
import math
import re
import time
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Iterator, Protocol

from vasty import timeutil
from vasty.errors import VastyError
from vasty.models import Balance, Charges, CreateRequest, Instance, Offer, OfferQuery, SshKey


class ProviderTimeout(VastyError):
    """A create call timed out or lost its connection; the instance may exist."""

    def __init__(self, message: str) -> None:
        super().__init__("provider_error", message, "Run vasty status.")


class Provider(Protocol):
    """The ten provider functions plus the latest response's `Date` header."""

    def search_offers(self, query: OfferQuery) -> list[Offer]: ...

    def create(self, request: CreateRequest) -> int:
        """Create an instance with SDK retries off and return its instance id.

        Raise `ProviderTimeout` on a timeout or connection error.
        """
        ...

    def list_instances(self) -> list[Instance]:
        """List every instance on the account, following `next_token`."""
        ...

    def get_instance(self, instance_id: int) -> Instance | None: ...

    def destroy(self, instance_id: int) -> None: ...

    def set_label(self, instance_id: int, label: str) -> None: ...

    def charges(self, start: int, end: int) -> Charges:
        """Return billed charges between two epoch seconds for every instance."""
        ...

    def balance(self) -> Balance: ...

    def list_ssh_keys(self) -> list[SshKey]: ...

    def attach_ssh_key(self, public_key: str, instance_id: int | None = None) -> None:
        """Register the key on the account, or attach it to one instance when an id is given."""
        ...

    def last_date(self) -> tuple[float, float] | None:
        """Return the latest response's `Date` header as epoch seconds and the local monotonic time it arrived."""
        ...


ClientFactory = Callable[[int], Any]
"""Build an HTTP client for a retry count.

The client exposes `get`, `post`, `put` and `delete` with the signature of
`vastai.api.client.VastClient` and returns `requests.Response` objects.
"""

DEFAULT_RETRY = 3
CREATE_RETRY = 1
PAGE_LIMIT = 1000

# Short GPU names that map to a Vast `gpu_name` family.
GPU_FAMILIES: dict[str, tuple[str, ...]] = {
    "A100": ("A100 PCIE", "A100 SXM4", "A100X"),
    "H100": ("H100 PCIE", "H100 SXM", "H100 NVL"),
    "H200": ("H200", "H200 NVL"),
    "V100": ("Tesla V100",),
    "6000ADA": ("RTX 6000Ada",),
}

_CONSUMER = re.compile(r"(?:RTX|GTX)?(\d{4})(TI)?")
_WORKSTATION = re.compile(r"(?:RTX)?A(\d{4})")
_SINGLE_TOKEN = re.compile(r"[A-Za-z]+\d+[A-Za-z]*")


def gpu_name_filter(name: str) -> dict[str, Any]:
    """Map a `--gpu` value to a `gpu_name` filter.

    The rule matches on the name upper-cased with spaces, `_` and `-` removed:

    - A family key in `GPU_FAMILIES` (`A100`, `H100`, `H200`, `V100`, `6000ADA`),
      with an optional `RTX` prefix, maps to an `in` filter over the family's
      names, or `eq` for a one-name family.
    - Four digits, with an optional `RTX`/`GTX` prefix and `TI` suffix, map to
      `RTX NNNN` (`GTX NNNN` for 1xxx), plus ` Ti`. `4090` becomes `RTX 4090`.
    - `A` plus four digits, with an optional `RTX` prefix, maps to `RTX A####`.
      `A6000` becomes `RTX A6000`.
    - One letters-then-digits token is upper-cased. `l40s` becomes `L40S`.
    - Anything else passes through with `_` replaced by a space.
    """
    compact = re.sub(r"[\s_-]+", "", name).upper()
    family = GPU_FAMILIES.get(compact) or GPU_FAMILIES.get(compact.removeprefix("RTX"))
    if family is not None:
        return {"eq": family[0]} if len(family) == 1 else {"in": list(family)}
    match = _CONSUMER.fullmatch(compact)
    if match:
        prefix = "GTX" if match.group(1).startswith("1") else "RTX"
        suffix = " Ti" if match.group(2) else ""
        return {"eq": f"{prefix} {match.group(1)}{suffix}"}
    match = _WORKSTATION.fullmatch(compact)
    if match:
        return {"eq": f"RTX A{match.group(1)}"}
    plain = name.replace("_", " ").strip()
    if _SINGLE_TOKEN.fullmatch(plain):
        return {"eq": plain.upper()}
    return {"eq": plain}


def build_offer_query(query: OfferQuery) -> dict[str, Any]:
    """Build the `/bundles/` filter dict for `OfferQuery`.

    The dict carries the SDK's default basics because search runs with
    `no_default=True`. `gpu_ram` uses the SDK's 1000 MB per GB multiplier.
    """
    q: dict[str, Any] = {
        "verified": {"eq": True},
        "external": {"eq": False},
        "rentable": {"eq": True},
        "rented": {"eq": False},
        "num_gpus": {"eq": query.gpus},
        "dph_total": {"lte": float(query.max_price)},
        "disk_space": {"gte": query.disk_gb},
    }
    if query.gpu:
        q["gpu_name"] = gpu_name_filter(query.gpu)
    if query.vram_min_gb is not None:
        q["gpu_ram"] = {"gte": query.vram_min_gb * 1000}
    if query.region:
        q["geolocation"] = _region_filter(query.region)
    if query.cuda is not None:
        q["cuda_max_good"] = {"gte": query.cuda}
    return q


def _region_filter(region: str) -> dict[str, Any]:
    from vastai.utils import _regions

    code = region.strip().upper()
    countries = _regions.get(code)
    if isinstance(countries, str):
        return {"in": countries.split(",")}
    return {"eq": code}


def normalize_ports(raw: object) -> dict[int, int]:
    """Turn Docker-style `{"22/tcp": [{"HostPort": "41022"}]}` into `{22: 41022}`.

    Absent, empty or unparsable input gives `{}`. UDP entries are skipped.
    """
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[int, int] = {}
    for key, bindings in raw.items():
        port_text, _, proto = str(key).partition("/")
        if proto and proto != "tcp":
            continue
        inner = _to_int(port_text)
        if inner is None or not isinstance(bindings, list):
            continue
        for binding in bindings:
            host = _to_int(binding.get("HostPort")) if isinstance(binding, dict) else None
            if host is not None:
                out[inner] = host
                break
    return out


def normalize_offer(row: dict[str, Any]) -> Offer | None:
    """Return an `Offer` for one `/bundles/` row, or None when it lacks id, name or price."""
    offer_id = _to_int(row.get("id"))
    price = _to_decimal(row.get("dph_total"))
    name = _to_str(row.get("gpu_name"))
    if offer_id is None or price is None or name is None:
        return None
    reliability = _to_float(row.get("reliability"))
    if reliability is None:
        reliability = _to_float(row.get("reliability2"))
    return Offer(
        id=offer_id,
        gpu_name=name,
        num_gpus=_to_int(row.get("num_gpus")) or 0,
        gpu_ram_gb=_gb(row.get("gpu_ram")) or 0.0,
        dph_total=price,
        reliability=reliability or 0.0,
        inet_down=_to_float(row.get("inet_down")) or 0.0,
        direct_port_count=_to_int(row.get("direct_port_count")) or 0,
        geolocation=_to_str(row.get("geolocation")),
    )


def normalize_instance(row: dict[str, Any]) -> Instance | None:
    """Return an `Instance` for one instance row, or None when it has no id."""
    instance_id = _to_int(row.get("id"))
    if instance_id is None:
        return None
    return Instance(
        id=instance_id,
        label=_to_str(row.get("label"), strip=False),
        actual_status=_to_str(row.get("actual_status")),
        gpu_name=_to_str(row.get("gpu_name")),
        num_gpus=_to_int(row.get("num_gpus")) or 0,
        gpu_ram_gb=_gb(row.get("gpu_ram")),
        dph_total=_to_decimal(row.get("dph_total")) or Decimal("0"),
        public_ipaddr=_to_str(row.get("public_ipaddr")),
        ssh_host=_to_str(row.get("ssh_host")),
        ssh_port=_to_int(row.get("ssh_port")),
        ports=normalize_ports(row.get("ports")),
        image=_to_str(row.get("image_uuid")),
        runtype=_to_str(row.get("image_runtype")),
        cuda_max_good=_to_float(row.get("cuda_max_good")),
    )


def parse_charges(rows: list[Any], end: int) -> Charges:
    """Sum top-level instance charge rows per instance and for today.

    Rows whose `type` is other than `instance` are skipped. `today` sums the
    rows whose `start`, else `end`, falls on or after 00:00 UTC of the day
    that holds `end`. A row with neither time counts toward today.
    """
    today_start = timeutil.day_start(int(end))
    per_instance: dict[int, Decimal] = {}
    today = Decimal("0")
    for row in rows:
        if not isinstance(row, dict) or row.get("type", "instance") != "instance":
            continue
        amount = _to_decimal(row.get("amount"))
        if amount is None:
            continue
        instance_id = _charge_instance_id(row)
        if instance_id is not None:
            per_instance[instance_id] = per_instance.get(instance_id, Decimal("0")) + amount
        at = _to_int(row.get("start"))
        if at is None:
            at = _to_int(row.get("end"))
        if at is None or at >= today_start:
            today += amount
    return Charges(per_instance=per_instance, today=today)


def _charge_instance_id(row: dict[str, Any]) -> int | None:
    source = row.get("source")
    if isinstance(source, int) and not isinstance(source, bool):
        return source
    if isinstance(source, str):
        found = _to_int(source.rsplit("-", 1)[-1])
        if found is not None:
            return found
    metadata = row.get("metadata")
    if isinstance(metadata, dict):
        return _to_int(metadata.get("instance_id"))
    return None


def normalize_ssh_keys(data: object) -> list[SshKey]:
    """Read SSH keys from a list or from a dict holding `ssh_keys`, `keys` or `results`."""
    rows: object = data
    if isinstance(data, dict):
        rows = next(
            (data[k] for k in ("ssh_keys", "keys", "results") if isinstance(data.get(k), list)),
            [],
        )
    if not isinstance(rows, list):
        return []
    out: list[SshKey] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        key_id = _to_int(row.get("id"))
        key = next(
            (_to_str(row.get(k)) for k in ("public_key", "ssh_key", "key") if _to_str(row.get(k))),
            None,
        )
        if key_id is not None and key is not None:
            out.append(SshKey(id=key_id, public_key=key))
    return out


class _Recorder:
    """Forward calls to an HTTP client and report each response."""

    def __init__(self, inner: Any, on_response: Callable[[Any], None]) -> None:
        self._inner = inner
        self._on_response = on_response

    def get(self, subpath: str, query_args: Any = None, json_data: Any = None,
            timeout: float | None = None) -> Any:
        return self._send("get", subpath, query_args, json_data, timeout)

    def post(self, subpath: str, query_args: Any = None, json_data: Any = None,
             timeout: float | None = None) -> Any:
        return self._send("post", subpath, query_args, json_data, timeout)

    def put(self, subpath: str, query_args: Any = None, json_data: Any = None,
            timeout: float | None = None) -> Any:
        return self._send("put", subpath, query_args, json_data, timeout)

    def delete(self, subpath: str, query_args: Any = None, json_data: Any = None,
               timeout: float | None = None) -> Any:
        return self._send("delete", subpath, query_args, json_data, timeout)

    def _send(self, method: str, subpath: str, query_args: Any, json_data: Any,
              timeout: float | None) -> Any:
        response = getattr(self._inner, method)(
            subpath, query_args=query_args, json_data=json_data, timeout=timeout
        )
        self._on_response(response)
        return response


class VastProvider:
    """`Provider` backed by the `vastai` SDK.

    `client_factory` builds the HTTP client for a retry count; tests pass a
    fake. The default builds `vastai.api.client.VastClient`. Every client is
    wrapped so each response's `Date` header feeds `last_date`.
    """

    def __init__(
        self,
        api_key: str,
        client_factory: ClientFactory | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._api_key = api_key
        self._factory = client_factory or self._sdk_client
        self._monotonic = monotonic
        self._clients: dict[int, _Recorder] = {}
        self._date: tuple[float, float] | None = None

    def _sdk_client(self, retry: int) -> Any:
        from vastai.api.client import VastClient

        return VastClient(api_key=self._api_key, retry=retry)

    def _client(self, retry: int = DEFAULT_RETRY) -> _Recorder:
        client = self._clients.get(retry)
        if client is None:
            client = _Recorder(self._factory(retry), self._record)
            self._clients[retry] = client
        return client

    def _record(self, response: Any) -> None:
        headers = getattr(response, "headers", None)
        value = headers.get("Date") if headers is not None else None
        epoch = timeutil.parse_http_date(value if isinstance(value, str) else None)
        self._date = None if epoch is None else (epoch, self._monotonic())

    def search_offers(self, query: OfferQuery) -> list[Offer]:
        with _guard("search"):
            from vastai.api import offers

            rows = offers.search_offers(
                self._client(),
                query=build_offer_query(query),
                order=[["reliability", "desc"]],
                storage=float(query.disk_gb),
                no_default=True,
            )
            if not isinstance(rows, list):
                raise _unexpected("search", "offers is not a list")
            found = [normalize_offer(r) for r in rows if isinstance(r, dict)]
            return [o for o in found if o is not None]

    def create(self, request: CreateRequest) -> int:
        with _guard("create"):
            from vastai.api import instances

            env: dict[str, str] = {f"-p {p}:{p}": "1" for p in request.ports}
            env.update(request.env)
            payload = instances.build_create_instance_payload(
                image=request.image,
                disk=float(request.disk_gb),
                env=env,
                label=request.label,
                onstart_cmd=request.onstart,
                ssh=True,
                direct=request.runtype == "ssh_direct",
            )
            client = self._client(CREATE_RETRY)
        try:
            data = instances.create_instance_from_payload(client, request.offer_id, payload)
        except Exception as exc:
            if _may_have_created(exc):
                raise ProviderTimeout(f"Vast create may have succeeded: {_describe(exc)}.") from exc
            raise _provider_error("create", exc) from exc
        _check_success(data, "create")
        new_id = _to_int(data.get("new_contract")) if isinstance(data, dict) else None
        if new_id is None:
            raise ProviderTimeout("Vast create returned no new_contract.")
        return new_id

    def list_instances(self) -> list[Instance]:
        with _guard("list instances"):
            from vastai.api import instances

            params: dict[str, Any] = {
                "select_filters": {},
                "order_by": [{"col": "id", "dir": "asc"}],
                "limit": 25,
            }
            out: list[Instance] = []
            seen: set[str] = set()
            for _ in range(PAGE_LIMIT):
                data = instances.show_instances_v1(self._client(), params)
                if not isinstance(data, dict):
                    raise _unexpected("list instances", "response is not an object")
                for row in data.get("instances") or []:
                    if isinstance(row, dict):
                        inst = normalize_instance(row)
                        if inst is not None:
                            out.append(inst)
                token = data.get("next_token")
                if not token or str(token) in seen:
                    break
                seen.add(str(token))
                params["after_token"] = token
            return out

    def get_instance(self, instance_id: int) -> Instance | None:
        with _guard("get instance"):
            response = self._client().get(f"/instances/{instance_id}/", query_args={"owner": "me"})
            if response.status_code == 404:
                return None
            response.raise_for_status()
            data = response.json()
            row = data.get("instances") if isinstance(data, dict) else None
            if isinstance(row, list):
                row = next((r for r in row if isinstance(r, dict)
                            and _to_int(r.get("id")) == instance_id), None)
            if not isinstance(row, dict):
                return None
            return normalize_instance(row)

    def destroy(self, instance_id: int) -> None:
        with _guard("destroy"):
            from vastai.api import instances

            _check_success(instances.destroy_instance(self._client(), instance_id), "destroy")

    def set_label(self, instance_id: int, label: str) -> None:
        with _guard("set label"):
            from vastai.api import instances

            data = instances.label_instance(self._client(), instance_id, label)
            _check_success(data, "set label")

    def charges(self, start: int, end: int) -> Charges:
        with _guard("charges"):
            from vastai.api import billing

            params: dict[str, Any] = {
                "charges": True,
                "start_date": int(start),
                "end_date": int(end),
                "limit": 100,
                "charge_type": ["instance"],
            }
            rows: list[Any] = []
            seen: set[str] = set()
            for _ in range(PAGE_LIMIT):
                data = billing.show_invoices_v1(self._client(), params)
                if not isinstance(data, dict):
                    raise _unexpected("charges", "response is not an object")
                page = data.get("results") or []
                if not isinstance(page, list):
                    raise _unexpected("charges", "results is not a list")
                rows.extend(page)
                token = data.get("next_token")
                if not token or str(token) in seen:
                    break
                seen.add(str(token))
                params["next_token"] = token
            return parse_charges(rows, int(end))

    def balance(self) -> Balance:
        with _guard("balance"):
            from vastai.api import billing

            data = billing.show_user(self._client())
            if not isinstance(data, dict):
                raise _unexpected("balance", "response is not an object")
            balance = _to_decimal(data.get("balance"))
            credit = _to_decimal(data.get("credit"))
            if balance is None:
                raise _unexpected("balance", "no balance field")
            if credit is None:
                raise _unexpected("balance", "no credit field")
            return Balance(balance=balance, credit=credit)

    def list_ssh_keys(self) -> list[SshKey]:
        with _guard("list ssh keys"):
            from vastai.api import keys

            return normalize_ssh_keys(keys.show_ssh_keys(self._client()))

    def attach_ssh_key(self, public_key: str, instance_id: int | None = None) -> None:
        with _guard("attach ssh key"):
            from vastai.api import keys

            if instance_id is None:
                data = keys.create_ssh_key(self._client(), public_key)
            else:
                data = keys.attach_ssh(self._client(), instance_id, public_key)
            _check_success(data, "attach ssh key")

    def last_date(self) -> tuple[float, float] | None:
        return self._date


@contextmanager
def _guard(action: str) -> Iterator[None]:
    """Turn every failure inside the block into a `provider_error`."""
    try:
        yield
    except VastyError:
        raise
    except Exception as exc:
        raise _provider_error(action, exc) from exc


def _may_have_created(exc: BaseException) -> bool:
    """Return True when a create failure leaves the instance's existence unknown."""
    import requests

    if isinstance(exc, requests.exceptions.HTTPError):
        response = exc.response
        return response is not None and response.status_code in (502, 503, 504)
    if isinstance(exc, ValueError):
        return True
    return isinstance(
        exc,
        (
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        ),
    )


def _provider_error(action: str, exc: BaseException) -> VastyError:
    import requests

    if isinstance(exc, requests.exceptions.HTTPError) and exc.response is not None:
        return _http_error(action, exc.response)
    if isinstance(exc, (requests.exceptions.Timeout, requests.exceptions.ConnectionError)):
        return VastyError(
            "provider_error",
            f"Vast {action} failed: {_describe(exc)}.",
            "Check the network and retry.",
            {"action": action},
        )
    if isinstance(exc, requests.exceptions.RequestException):
        return VastyError(
            "provider_error",
            f"Vast {action} request failed: {_describe(exc)}.",
            "Retry the command.",
            {"action": action},
        )
    return _unexpected(action, _describe(exc))


def _http_error(action: str, response: Any) -> VastyError:
    status = int(response.status_code)
    body = _body_message(response)
    details: dict[str, Any] = {"action": action, "status": status}
    if status == 429 and _is_quota(response):
        return VastyError(
            "provider_error",
            f"Vast search quota exceeded: {body}",
            "Retry after 00:00 UTC, when the daily quota resets.",
            {**details, "reason": "search_quota_exceeded"},
        )
    if status == 429:
        hint = "Wait a minute and retry."
    elif status in (401, 403):
        hint = "Check the Vast API key."
    elif status == 404:
        hint = "Run vasty status; Vast also returns 404 for an unauthorized key."
    elif status >= 500:
        hint = "Retry later; Vast returned a server error."
    else:
        hint = "Check the request and retry."
    return VastyError("provider_error", f"Vast {action} returned HTTP {status}: {body}", hint, details)


def _is_quota(response: Any) -> bool:
    try:
        data = response.json()
    except ValueError:
        return "search_quota_exceeded" in str(getattr(response, "text", ""))
    return isinstance(data, dict) and data.get("error") == "search_quota_exceeded"


def _body_message(response: Any) -> str:
    try:
        data = response.json()
    except ValueError:
        text = str(getattr(response, "text", "") or "").strip()
        return text[:200] or "no body"
    if isinstance(data, dict):
        for key in ("msg", "error", "detail", "message"):
            if data.get(key):
                return str(data[key])[:200]
    return json.dumps(data)[:200]


def _check_success(data: object, action: str) -> None:
    """Raise `provider_error` when a 2xx body reports `success: false`."""
    if isinstance(data, dict) and data.get("success") is False:
        message = data.get("msg") or data.get("error") or "success is false"
        raise VastyError(
            "provider_error",
            f"Vast {action} failed: {message}",
            "Check the request and retry.",
            {"action": action, "response": {k: data[k] for k in ("error", "msg") if k in data}},
        )


def _unexpected(action: str, why: str) -> VastyError:
    return VastyError(
        "provider_error",
        f"Vast {action} returned an unexpected response: {why}.",
        "Retry; report the response if it repeats.",
        {"action": action},
    )


def _describe(exc: BaseException) -> str:
    text = str(exc).strip()
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


def _to_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if math.isfinite(value) else None
    if isinstance(value, str):
        text = value.strip()
        if re.fullmatch(r"-?\d+", text):
            return int(text)
        return _to_int(_to_float(text))
    return None


def _to_float(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        result = float(value)
    elif isinstance(value, str):
        try:
            result = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    return result if math.isfinite(result) else None


def _to_decimal(value: object) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float, str, Decimal)):
        try:
            result = Decimal(str(value).strip())
        except InvalidOperation:
            return None
        return result if result.is_finite() else None
    return None


def _to_str(value: object, strip: bool = True) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip() if strip else value
    return text if text.strip() else None


def _gb(value: object) -> float | None:
    mb = _to_float(value)
    return None if mb is None else mb / 1000
