import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import AgentChatPage from "../app/agent/page";

// Mock EventSource (SSE)
class MockEventSource {
  onmessage: ((e: MessageEvent) => void) | null = null;
  onerror: ((e: Event) => void) | null = null;
  onopen: ((e: Event) => void) | null = null;
  close = vi.fn();
  static instances: MockEventSource[] = [];
  constructor(public url: string) {
    MockEventSource.instances.push(this);
  }
  emit(data: string) {
    this.onmessage?.({ data } as MessageEvent);
  }
  emitError() {
    this.onerror?.(new Event("error"));
  }
}
(global as unknown as { EventSource: typeof MockEventSource }).EventSource = MockEventSource;

// Mock fetch
const mockFetch = vi.fn();
global.fetch = mockFetch;

// Mock next-auth
vi.mock("next-auth/react", () => ({
  useSession: () => ({
    data: { user: { name: "Jordan", email: "jordan@bank.com", role: "data_scientist" } },
    status: "authenticated",
  }),
}));

describe("AgentChatPage", () => {
  beforeEach(() => {
    MockEventSource.instances.length = 0;
    mockFetch.mockReset();
    mockFetch.mockResolvedValue({ ok: true, json: async () => ({ session_id: "sess-001" }) });
  });

  it("renders the chat interface", () => {
    render(<AgentChatPage />);
    expect(screen.getByPlaceholderText(/ask/i)).toBeDefined();
    expect(screen.getByText(/data analyst/i)).toBeDefined();
  });

  it("shows persona toggle buttons", () => {
    render(<AgentChatPage />);
    expect(screen.getByText(/data analyst/i)).toBeDefined();
    expect(screen.getByText(/business analyst/i)).toBeDefined();
  });

  it("sends a message and shows streaming response", async () => {
    render(<AgentChatPage />);
    const input = screen.getByPlaceholderText(/ask/i);
    fireEvent.change(input, { target: { value: "What is the approval rate?" } });
    fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() => {
      const instances = MockEventSource.instances;
      expect(instances.length).toBeGreaterThan(0);
    });

    // Simulate SSE tokens
    const es = MockEventSource.instances[0];
    es.emit(JSON.stringify({ token: "The " }));
    es.emit(JSON.stringify({ token: "approval " }));
    es.emit(JSON.stringify({ token: "rate " }));
    es.emit(JSON.stringify({ token: "is 72%." }));
    es.emit("[DONE]");

    await waitFor(() => {
      expect(screen.getByText(/The approval rate is 72%./)).toBeDefined();
    });
  });

  it("renders SQL blocks as collapsible", async () => {
    render(<AgentChatPage />);
    const input = screen.getByPlaceholderText(/ask/i);
    fireEvent.change(input, { target: { value: "Show me the SQL query" } });
    fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() => expect(MockEventSource.instances.length).toBeGreaterThan(0));

    const es = MockEventSource.instances[0];
    es.emit(JSON.stringify({ token: "Here is the query:\n```sql\nSELECT * FROM decisions;\n```" }));
    es.emit("[DONE]");

    await waitFor(() => {
      expect(screen.getByText(/show sql/i)).toBeDefined();
    });
  });

  it("switches persona", () => {
    render(<AgentChatPage />);
    const bizBtn = screen.getByText(/business analyst/i);
    fireEvent.click(bizBtn);
    expect(screen.getByText(/business analyst/i).closest("button")?.className).toContain("bg-");
  });

  it("clears conversation on new chat", async () => {
    render(<AgentChatPage />);
    const input = screen.getByPlaceholderText(/ask/i);
    fireEvent.change(input, { target: { value: "Test message" } });
    fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() => expect(MockEventSource.instances.length).toBeGreaterThan(0));
    MockEventSource.instances[0].emit(JSON.stringify({ token: "Answer" }));
    MockEventSource.instances[0].emit("[DONE]");

    await waitFor(() => screen.getByText("Answer"));

    const newChatBtn = screen.getByText(/new chat/i);
    fireEvent.click(newChatBtn);
    expect(screen.queryByText("Answer")).toBeNull();
  });
});
