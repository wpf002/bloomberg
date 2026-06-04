import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// React Testing Library mounts into a shared document; unmount + clear DOM
// after every test so state and listeners don't leak across cases.
afterEach(() => {
  cleanup();
});
