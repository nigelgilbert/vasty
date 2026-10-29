"""`VastProvider` against a fake HTTP layer and a patched SDK session. No network."""

from __future__ import annotations

import json
import subprocess
import sys
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Callable

import pytest
import requests

from vasty.errors import VastyError
from vasty.models import CreateRequest, OfferQuery
from vasty.provider import (
    ProviderTimeout,
    VastProvider,
    build_offer_query,
    gpu_name_filter,
    normalize_ports,
    parse_charges,
)

DATE = "Thu, 29 Oct 2026 01:00:00 GMT"
DATE_EPOCH = 1_793_235_600.0

Call = tuple[str, str, Any, Any]
Handler = Callable[[str, str, Any, Any], "requests.Response | BaseException"]


def resp(status: int = 200, body: Any = None, text: str | None = None,
         date: str | None = DATE) -> requests.Response:
    r = requests.Response()
    r.status_code = status
    raw = text if text is not None else json.dumps(body if body is not None else {})
    r._content = raw.encode()
    if date is not None:
        r.headers["Date"] = date
    r.url = "https://console.vast.ai/api/v0/test"
    return r


class FakeHttp:
    """Stands in for `VastClient`: records calls and answers from a handler."""

    def __init__(self, handler: Handler) -> None:
        self.handler = handler
        self.calls: list[Call] = []

    def _do(self, method: str, subpath: str, query_args: Any, json_data: Any) -> requests.Response:
        self.calls.append((method, subpath, query_args, json_data))
        out = self.handler(method, subpath, query_args, json_data)
        if isinstance(out, BaseException):
            raise out
        return out

    def get(self, subpath: str, query_args: Any = None, json_data: Any = None,
            timeout: float | None = None) -> requests.Response:
        return self._do("GET", subpath, query_args, json_data)

    def post(self, subpath: str, query_args: Any = None, json_data: Any = None,
             timeout: float | None = None) -> requests.Response:
        return self._do("POST", subpath, query_args, json_data)

    def put(self, subpath: str, query_args: Any = None, json_data: Any = None,
            timeout: float | None = None) -> requests.Response:
        return self._do("PUT", subpath, query_args, json_data)

    def delete(self, subpath: str, query_args: Any = None, json_data: Any = None,
               timeout: float | None = None) -> requests.Response:
        return self._do("DELETE", subpath, query_args, json_data)


def make(handler: Handler, mono: float = 500.0) -> tuple[VastProvider, FakeHttp, list[int]]:
    http = FakeHttp(handler)
    retries: list[int] = []

    def factory(retry: int) -> FakeHttp:
        retries.append(retry)
        return http

    return VastProvider("test-key", client_factory=factory, monotonic=lambda: mono), http, retries


def always(r: requests.Response | BaseException) -> Handler:
    return lambda method, path, q, body: r


def request(runtype: str = "ssh_direct") -> CreateRequest:
    return CreateRequest(
        offer_id=77, image="vastai/base-image:cuda-12.4", disk_gb=50, label="vasty:v1 lease=l-7f3a",
        onstart="echo hi", ports=[22, 8000, 8080], runtype=runtype,  # type: ignore[arg-type]
        env={"FOO": "bar"},
    )


# Query building.


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("4090", {"eq": "RTX 4090"}),
        ("RTX_4090", {"eq": "RTX 4090"}),
        ("rtx 3090", {"eq": "RTX 3090"}),
        ("4070ti", {"eq": "RTX 4070 Ti"}),
        ("1080", {"eq": "GTX 1080"}),
        ("A6000", {"eq": "RTX A6000"}),
        ("RTX A5000", {"eq": "RTX A5000"}),
        ("l40s", {"eq": "L40S"}),
        ("A100", {"in": ["A100 PCIE", "A100 SXM4", "A100X"]}),
        ("h100", {"in": ["H100 PCIE", "H100 SXM", "H100 NVL"]}),
        ("A100_SXM4", {"eq": "A100 SXM4"}),
        ("RTX 6000Ada", {"eq": "RTX 6000Ada"}),
        ("6000ada", {"eq": "RTX 6000Ada"}),
        ("V100", {"eq": "Tesla V100"}),
    ],
)
def test_gpu_name_mapping(name: str, expected: dict[str, Any]) -> None:
    assert gpu_name_filter(name) == expected


def test_offer_query_dict() -> None:
    q = build_offer_query(OfferQuery(
        gpu="4090", vram_min_gb=24, gpus=2, disk_gb=80, max_price=Decimal("0.75"), region="NA",
    ))
    assert q == {
        "verified": {"eq": True},
        "external": {"eq": False},
        "rentable": {"eq": True},
        "rented": {"eq": False},
        "num_gpus": {"eq": 2},
        "dph_total": {"lte": 0.75},
        "disk_space": {"gte": 80},
        "gpu_name": {"eq": "RTX 4090"},
        "gpu_ram": {"gte": 24000},
        "geolocation": {"in": ["CA", "US"]},
    }


def test_offer_query_omits_unset_and_country_region() -> None:
    q = build_offer_query(OfferQuery(
        gpu=None, vram_min_gb=None, gpus=1, disk_gb=50, max_price=Decimal("1"), region="de",
    ))
    assert "gpu_name" not in q and "gpu_ram" not in q
    assert q["geolocation"] == {"eq": "DE"}


def test_search_posts_bundles_and_normalizes() -> None:
    rows = [
        {"id": 11, "gpu_name": "RTX 4090", "num_gpus": 1, "gpu_ram": 24564, "dph_total": 0.381,
         "reliability": 0.995, "inet_down": 812.5, "direct_port_count": 40,
         "geolocation": "Oregon, US"},
        {"id": 12, "gpu_name": "RTX 4090", "num_gpus": 1, "gpu_ram": 24564, "dph_total": "0.29",
         "reliability2": 0.9, "inet_down": None, "direct_port_count": None},
        {"id": None, "gpu_name": "RTX 4090", "dph_total": 0.1},
        "junk",
    ]
    provider, http, _ = make(always(resp(body={"offers": rows})))
    offers = provider.search_offers(OfferQuery(
        gpu="4090", vram_min_gb=None, gpus=1, disk_gb=50, max_price=Decimal("0.5"), region=None,
    ))
    method, path, _, body = http.calls[0]
    assert (method, path) == ("POST", "/bundles/")
    assert body["allocated_storage"] == 50.0
    assert body["type"] == "on-demand"
    assert body["gpu_name"] == {"eq": "RTX 4090"}
    assert body["dph_total"] == {"lte": 0.5}
    assert [o.id for o in offers] == [11, 12]
    first, second = offers
    assert first.dph_total == Decimal("0.381")
    assert first.gpu_ram_gb == pytest.approx(24.564)
    assert first.reliability == 0.995 and first.inet_down == 812.5
    assert first.direct_port_count == 40 and first.geolocation == "Oregon, US"
    assert second.dph_total == Decimal("0.29") and second.reliability == 0.9
    assert second.inet_down == 0.0 and second.direct_port_count == 0


def test_search_quota_error_is_surfaced() -> None:
    provider, http, _ = make(always(resp(429, {"error": "search_quota_exceeded", "msg": "quota"})))
    with pytest.raises(VastyError) as exc:
        provider.search_offers(OfferQuery(None, None, 1, 50, Decimal("1"), None))
    assert exc.value.code == "provider_error"
    assert exc.value.details is not None
    assert exc.value.details["reason"] == "search_quota_exceeded"
    assert "00:00 UTC" in exc.value.hint
    assert len(http.calls) == 1


# Normalization.


def test_normalize_ports() -> None:
    raw = {
        "22/tcp": [{"HostIp": "0.0.0.0", "HostPort": "41022"}, {"HostIp": "::", "HostPort": "41022"}],
        "8000/tcp": [{"HostIp": "0.0.0.0", "HostPort": "41080"}],
        "8080/tcp": None,
        "9000/udp": [{"HostPort": "49000"}],
    }
    assert normalize_ports(raw) == {22: 41022, 8000: 41080}
    assert normalize_ports(None) == {}
    assert normalize_ports({}) == {}
    assert normalize_ports(json.dumps({"22/tcp": [{"HostPort": "40022"}]})) == {22: 40022}
    assert normalize_ports("not json") == {}


def instance_row(iid: int, **kw: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": iid, "label": "vasty:v1 lease=l-1", "actual_status": "running", "gpu_name": "RTX 4090",
        "num_gpus": 1, "gpu_ram": 24564, "dph_total": 0.38, "public_ipaddr": "198.51.100.7\n",
        "ssh_host": "ssh4.vast.ai", "ssh_port": "31022", "image_uuid": "vastai/base",
        "image_runtype": "ssh_direc ssh_proxy", "extra_env": [["FOO", "bar"]],
        "ports": {"22/tcp": [{"HostIp": "0.0.0.0", "HostPort": "41022"}]},
    }
    row.update(kw)
    return row


def test_list_instances_follows_next_token() -> None:
    pages = {
        None: {"instances": [instance_row(1), instance_row(2, ports=None)], "next_token": "t1"},
        "t1": {"instances": [instance_row(3, actual_status=None, start_date=None)], "next_token": None},
    }

    def handler(method: str, path: str, q: Any, body: Any) -> requests.Response:
        assert (method, path) == ("GET", "/api/v1/instances/")
        return resp(body=pages[q.get("after_token")])

    provider, http, _ = make(handler)
    instances = provider.list_instances()
    assert [i.id for i in instances] == [1, 2, 3]
    assert len(http.calls) == 2
    assert http.calls[1][2]["after_token"] == "t1"
    first = instances[0]
    assert first.public_ipaddr == "198.51.100.7"
    assert first.ssh_port == 31022 and first.ports == {22: 41022}
    assert first.dph_total == Decimal("0.38") and isinstance(first.dph_total, Decimal)
    assert first.image == "vastai/base" and first.runtype == "ssh_direc ssh_proxy"
    assert instances[1].ports == {}
    assert instances[2].actual_status is None


def test_list_instances_stops_on_repeated_token() -> None:
    provider, http, _ = make(always(resp(body={"instances": [instance_row(1)], "next_token": "same"})))
    assert len(provider.list_instances()) == 2
    assert len(http.calls) == 2


def test_get_instance_404_and_missing_row() -> None:
    provider, _, _ = make(always(resp(404, {"error": "not_found"})))
    assert provider.get_instance(5) is None
    provider, _, _ = make(always(resp(body={"instances": None})))
    assert provider.get_instance(5) is None


def test_get_instance_row() -> None:
    provider, http, _ = make(always(resp(body={"instances": instance_row(5)})))
    inst = provider.get_instance(5)
    assert inst is not None and inst.id == 5 and inst.ports == {22: 41022}
    assert http.calls[0][:3] == ("GET", "/instances/5/", {"owner": "me"})


# Create.


@pytest.mark.parametrize(("runtype", "sent"), [("ssh_direct", "ssh_direc ssh_proxy"),
                                               ("ssh_proxy", "ssh_proxy")])
def test_create_payload(runtype: str, sent: str) -> None:
    provider, http, retries = make(always(resp(body={"success": True, "new_contract": 4242})))
    assert provider.create(request(runtype)) == 4242
    assert retries == [1]
    method, path, _, body = http.calls[0]
    assert (method, path) == ("PUT", "/asks/77/")
    assert body["image"] == "vastai/base-image:cuda-12.4"
    assert body["disk"] == 50.0
    assert body["label"] == "vasty:v1 lease=l-7f3a"
    assert body["onstart"] == "echo hi"
    assert body["runtype"] == sent
    assert body["env"] == {"-p 22:22": "1", "-p 8000:8000": "1", "-p 8080:8080": "1", "FOO": "bar"}


@pytest.mark.parametrize(
    "failure",
    [
        requests.exceptions.ReadTimeout("read timed out"),
        requests.exceptions.ConnectionError("reset"),
        resp(504, text="<html>gateway timeout</html>"),
        resp(200, text="not json"),
        resp(200, {"success": True}),
    ],
)
def test_create_unknown_outcome_raises_provider_timeout(failure: Any) -> None:
    provider, http, _ = make(always(failure))
    with pytest.raises(ProviderTimeout) as exc:
        provider.create(request())
    assert exc.value.code == "provider_error"
    assert len(http.calls) == 1


@pytest.mark.parametrize("failure", [resp(200, {"success": False, "msg": "offer taken"}),
                                     resp(400, {"error": "invalid_args", "msg": "bad image"})])
def test_create_rejection_is_provider_error(failure: requests.Response) -> None:
    provider, _, _ = make(always(failure))
    with pytest.raises(VastyError) as exc:
        provider.create(request())
    assert not isinstance(exc.value, ProviderTimeout)
    assert exc.value.code == "provider_error"


# The real SDK client with its session patched.


class SessionStub:
    def __init__(self, outcomes: list[requests.Response | BaseException]) -> None:
        self.outcomes = outcomes
        self.sent: list[Any] = []

    def send(self, _session: Any, prep: Any, **kw: Any) -> requests.Response:
        self.sent.append(prep)
        out = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(out, BaseException):
            raise out
        return out


@pytest.fixture
def session(monkeypatch: pytest.MonkeyPatch) -> Callable[[list[Any]], SessionStub]:
    import vastai.api.client as client_mod

    def install(outcomes: list[Any]) -> SessionStub:
        stub = SessionStub(outcomes)
        monkeypatch.setattr(client_mod.VastSession, "send",
                            lambda self, prep, **kw: stub.send(self, prep, **kw))
        monkeypatch.setattr(client_mod.time, "sleep", lambda s: None)
        return stub

    return install


def test_sdk_create_sends_once_on_timeout(session: Callable[[list[Any]], SessionStub]) -> None:
    stub = session([requests.exceptions.ConnectTimeout("connect timed out")])
    with pytest.raises(ProviderTimeout):
        VastProvider("test-key").create(request())
    assert len(stub.sent) == 1
    assert stub.sent[0].method == "PUT"
    assert stub.sent[0].url.endswith("/api/v0/asks/77/")
    assert stub.sent[0].headers["Authorization"] == "Bearer test-key"


def test_sdk_other_calls_keep_retries(session: Callable[[list[Any]], SessionStub]) -> None:
    stub = session([resp(503, text="busy"), resp(503, text="busy"),
                    resp(body={"instances": [], "next_token": None})])
    provider = VastProvider("test-key", monotonic=lambda: 9.0)
    assert provider.list_instances() == []
    assert len(stub.sent) == 3
    assert provider.last_date() == (DATE_EPOCH, 9.0)


def test_sdk_search_quota_is_not_retried(session: Callable[[list[Any]], SessionStub]) -> None:
    stub = session([resp(429, {"error": "search_quota_exceeded"})])
    with pytest.raises(VastyError):
        VastProvider("test-key").search_offers(OfferQuery(None, None, 1, 50, Decimal("1"), None))
    assert len(stub.sent) == 1


# Error mapping.


@pytest.mark.parametrize(
    ("failure", "hint_part", "status"),
    [
        (resp(401, {"error": "auth"}), "API key", 401),
        (resp(403, text="Forbidden"), "API key", 403),
        (resp(429, text="Too Many Requests"), "retry", 429),
        (resp(500, text="boom"), "server error", 500),
        (resp(404, {"msg": "no such instance"}), "unauthorized", 404),
    ],
)
def test_http_errors_map_to_provider_error(failure: requests.Response, hint_part: str,
                                           status: int) -> None:
    provider, _, _ = make(always(failure))
    with pytest.raises(VastyError) as exc:
        provider.destroy(5)
    assert exc.value.code == "provider_error"
    assert hint_part in exc.value.hint
    assert exc.value.details is not None and exc.value.details["status"] == status


def test_transport_and_shape_errors_map_to_provider_error() -> None:
    provider, _, _ = make(always(requests.exceptions.ConnectionError("down")))
    with pytest.raises(VastyError) as exc:
        provider.list_instances()
    assert exc.value.code == "provider_error" and not isinstance(exc.value, ProviderTimeout)
    assert "network" in exc.value.hint

    provider, _, _ = make(always(resp(200, text="<html>")))
    with pytest.raises(VastyError) as exc:
        provider.list_ssh_keys()
    assert exc.value.code == "provider_error"

    provider, _, _ = make(always(resp(body={"success": False, "msg": "nope"})))
    with pytest.raises(VastyError) as exc:
        provider.set_label(5, "x")
    assert "nope" in exc.value.message


# Date header.


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ({"Date": DATE}, (DATE_EPOCH, 7.0)),
        ({"Date": None}, None),
        ({"Date": ""}, None),
        ({"Date": "yesterday-ish"}, None),
        ({"Date": 1_793_235_600}, None),
        ({"Date": "Mon, 01 Jan 100000000000000000000 00:00:00 GMT"}, None),
        ({}, None),
        (None, None),
    ],
)
def test_record_reads_date_header(headers: dict[str, Any] | None,
                                  expected: tuple[float, float] | None) -> None:
    provider = VastProvider("test-key", client_factory=lambda retry: None, monotonic=lambda: 7.0)
    provider._record(SimpleNamespace(headers=headers))
    assert provider.last_date() == expected


def test_last_date_tracks_latest_response() -> None:
    responses = [resp(body={"balance": 3}), resp(body={"balance": 3}, date=None),
                 resp(body={"balance": 3}, date="garbage")]
    provider, _, _ = make(lambda m, p, q, b: responses.pop(0), mono=42.0)
    assert provider.last_date() is None
    provider.balance()
    assert provider.last_date() == (DATE_EPOCH, 42.0)
    provider.balance()
    assert provider.last_date() is None
    provider.balance()
    assert provider.last_date() is None


# Charges, balance and keys.


def test_charges_pages_and_parses() -> None:
    pages = {
        None: {"results": [
            {"type": "instance", "source": "instance-101", "amount": 0.5, "start": 1_793_232_000,
             "end": 1_793_235_000, "items": [{"amount": 0.4}, {"amount": 0.1}]},
            {"type": "instance", "source": "102", "amount": 1.25, "start": 1_793_232_000,
             "end": 1_793_236_000},
        ], "next_token": "n1"},
        "n1": {"results": [
            {"type": "instance", "source": None, "metadata": {"instance_id": 101}, "amount": "0.1",
             "start": 1_793_235_000, "end": 1_793_235_500},
        ], "next_token": None},
    }

    def handler(method: str, path: str, q: Any, body: Any) -> requests.Response:
        assert (method, path) == ("GET", "/api/v0/charges/")
        return resp(body=pages[q.get("after_token")])

    provider, http, _ = make(handler)
    start, end = 1_793_232_000, 1_793_239_000
    charges = provider.charges(start, end)
    assert charges.per_instance == {101: Decimal("0.6"), 102: Decimal("1.25")}
    assert charges.total == Decimal("1.85")
    assert charges.covered_through == 1_793_236_000
    first_q = http.calls[0][2]
    assert first_q["select_filters"]["day"] == {"gte": start, "lte": end}
    assert first_q["select_filters"]["type"] == {"in": ["instance"]}
    assert http.calls[1][2]["after_token"] == "n1"


def test_parse_charges_coverage_rules() -> None:
    assert parse_charges([], 100, 200).covered_through == 100
    assert parse_charges([{"source": "1", "amount": 1, "end": None}], 100, 200).covered_through is None
    assert parse_charges([{"source": "1", "amount": 1, "end": 500}], 100, 200).covered_through == 200
    volume = parse_charges([{"type": "volume", "source": "volume-5", "amount": 1, "end": 150}], 100, 200)
    assert volume.per_instance == {} and volume.covered_through == 100


def test_balance() -> None:
    provider, http, _ = make(always(resp(body={"balance": 12.5, "credit": 40})))
    assert provider.balance() == Decimal("12.5")
    assert http.calls[0][:2] == ("GET", "/users/current")
    provider, _, _ = make(always(resp(body={"credit": 40})))
    with pytest.raises(VastyError):
        provider.balance()


@pytest.mark.parametrize("body", [
    [{"id": 7, "public_key": "ssh-ed25519 AAAA me"}, {"id": 8}],
    {"ssh_keys": [{"id": 7, "ssh_key": "ssh-ed25519 AAAA me\n"}]},
])
def test_list_ssh_keys(body: Any) -> None:
    provider, http, _ = make(always(resp(body=body)))
    keys = provider.list_ssh_keys()
    assert [(k.id, k.public_key) for k in keys] == [(7, "ssh-ed25519 AAAA me")]
    assert http.calls[0][:2] == ("GET", "/ssh/")


def test_attach_ssh_key_account_and_instance() -> None:
    provider, http, _ = make(always(resp(body={"success": True})))
    provider.attach_ssh_key("ssh-ed25519 AAAA me")
    provider.attach_ssh_key("ssh-ed25519 AAAA me", 9)
    assert http.calls[0][:2] == ("POST", "/ssh/")
    assert http.calls[0][3] == {"ssh_key": "ssh-ed25519 AAAA me"}
    assert http.calls[1][:2] == ("POST", "/instances/9/ssh/")


def test_destroy_and_set_label_requests() -> None:
    provider, http, _ = make(always(resp(body={"success": True})))
    provider.destroy(5)
    provider.set_label(5, "vasty:v1 lease=l-1")
    assert http.calls[0][:2] == ("DELETE", "/instances/5/")
    assert http.calls[1][:2] == ("PUT", "/instances/5/")
    assert http.calls[1][3] == {"label": "vasty:v1 lease=l-1"}


# Import cost.


def test_import_does_not_load_vastai() -> None:
    code = "import sys, vasty.provider; print(sorted(m for m in ('vastai', 'requests') if m in sys.modules))"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"
