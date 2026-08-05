import pytest
from pydantic import ValidationError

from core.models import (
    Event,
    EventStatus,
    EventType,
    GraphEdge,
    GraphNode,
    HealthResponse,
    IngestRequest,
    NodeMetadata,
    NodeType,
    SearchRequest,
    SearchResponse,
    SearchResult,
    SourceRef,
)


class TestEventType:
    def test_values(self):
        assert EventType.interaction.value == "interaction"
        assert EventType.data.value == "data"
        assert EventType.source.value == "source"


class TestEventStatus:
    def test_values(self):
        assert EventStatus.raw.value == "raw"
        assert EventStatus.indexed.value == "indexed"
        assert EventStatus.linked.value == "linked"
        assert EventStatus.failed.value == "failed"
        assert EventStatus.skipped.value == "skipped"


class TestNodeType:
    def test_values(self):
        assert NodeType.system.value == "system"
        assert NodeType.interaction.value == "interaction"
        assert NodeType.data.value == "data"


class TestSourceRef:
    def test_minimal(self):
        ref = SourceRef(event_id="evt-1", valid=True, hash="abc123")
        assert ref.event_id == "evt-1"
        assert ref.valid is True
        assert ref.hash == "abc123"

    def test_missing_fields_raises(self):
        with pytest.raises(ValidationError):
            SourceRef()


class TestGraphNode:
    def test_minimal(self):
        node = GraphNode(
            node_id="n1",
            title="Test Node",
            content="Some content",
            node_type=NodeType.data,
            source_refs=[SourceRef(event_id="e1", valid=True, hash="h1")],
            confidence=0.8,
            metadata=NodeMetadata(evidence_quote="quote"),
        )
        assert node.node_id == "n1"
        assert node.title == "Test Node"
        assert node.confidence == 0.8

    def test_title_max_length(self):
        with pytest.raises(ValidationError):
            GraphNode(
                node_id="n1",
                title="x" * 61,
                content="c",
                node_type=NodeType.data,
                source_refs=[SourceRef(event_id="e1", valid=True, hash="h1")],
                confidence=0.5,
                metadata=NodeMetadata(evidence_quote="q"),
            )

    def test_confidence_bounds(self):
        with pytest.raises(ValidationError):
            GraphNode(
                node_id="n1",
                title="t",
                content="c",
                node_type=NodeType.data,
                source_refs=[],
                confidence=1.5,
                metadata=NodeMetadata(evidence_quote="q"),
            )
        with pytest.raises(ValidationError):
            GraphNode(
                node_id="n1",
                title="t",
                content="c",
                node_type=NodeType.data,
                source_refs=[],
                confidence=-0.1,
                metadata=NodeMetadata(evidence_quote="q"),
            )


class TestGraphEdge:
    def test_minimal(self):
        edge = GraphEdge(
            source="n1", target="n2", relation="related_to", evidence_event_id="e1"
        )
        assert edge.source == "n1"
        assert edge.target == "n2"
        assert edge.note == ""

    def test_with_note(self):
        edge = GraphEdge(
            source="n1",
            target="n2",
            relation="related_to",
            evidence_event_id="e1",
            note="optional note",
        )
        assert edge.note == "optional note"


class TestEvent:
    def test_minimal(self):
        ev = Event(
            event_id="e1",
            created_at="2026-01-01T00:00:00",
            raw_content="hello",
            content_hash="abc",
            event_type=EventType.interaction,
        )
        assert ev.status == EventStatus.raw
        assert ev.graph_refs == []

    def test_explicit_status(self):
        ev = Event(
            event_id="e1",
            created_at="2026-01-01T00:00:00",
            raw_content="hello",
            content_hash="abc",
            event_type=EventType.data,
            status=EventStatus.linked,
            graph_refs=["n1", "n2"],
        )
        assert ev.status == EventStatus.linked
        assert ev.graph_refs == ["n1", "n2"]


class TestIngestRequest:
    def test_default_event_type(self):
        req = IngestRequest(content="hello")
        assert req.event_type == "auto"

    def test_explicit_type(self):
        req = IngestRequest(content="hello", event_type="data")
        assert req.event_type == "data"


class TestSearchRequest:
    def test_defaults(self):
        req = SearchRequest(query="test")
        assert req.source_filter == "all"
        assert req.max_hops == 2
        assert req.limit == 20
        assert req.offset == 0


class TestSearchResult:
    def test_minimal(self):
        r = SearchResult(
            node_id="n1",
            title="t",
            snippet="snip",
            score=0.9,
            source_events=["e1"],
            source_type="interaction",
            confidence=0.8,
            degraded=False,
        )
        assert r.score == 0.9


class TestSearchResponse:
    def test_minimal(self):
        r = SearchResponse(results=[], total=0, degraded=False)
        assert r.total == 0


class TestHealthResponse:
    def test_defaults(self):
        h = HealthResponse(status="ok", ai_available=True, layers={})
        assert h.version == \"0.2.0\"
        assert h.last_event_at == ""
