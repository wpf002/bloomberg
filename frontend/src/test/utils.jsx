import { render } from "@testing-library/react";
import { I18nProvider } from "../i18n/index.jsx";

// Render a component inside the real I18nProvider so `t()` resolves to the
// English strings (the source-of-truth table) rather than echoing keys.
export function renderWithI18n(ui, options) {
  return render(ui, {
    wrapper: ({ children }) => <I18nProvider>{children}</I18nProvider>,
    ...options,
  });
}

// A controllable WebSocket double for components that open a stream on mount.
// Install with installFakeWebSocket() in beforeEach; drive lifecycle by hand.
export class FakeWebSocket {
  static instances = [];
  constructor(url) {
    this.url = url;
    this.sent = [];
    this.readyState = 0;
    FakeWebSocket.instances.push(this);
  }
  send(data) {
    this.sent.push(data);
  }
  close() {
    this.readyState = 3;
    this.onclose?.({});
  }
  _open() {
    this.readyState = 1;
    this.onopen?.({});
  }
  _emit(obj) {
    this.onmessage?.({ data: typeof obj === "string" ? obj : JSON.stringify(obj) });
  }
}
