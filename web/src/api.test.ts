import { describe, expect, it } from "vitest";

import { ApiRequestError, friendlyMessage } from "./api";

describe("friendlyMessage", () => {
  it("passes a rate_limited detail straight through (the server already phrases it in plain English)", () => {
    const message = friendlyMessage(429, {
      error: "rate_limited",
      detail: "rate limit: at most 5 runs/hour from one address",
    });
    expect(message).toBe("rate limit: at most 5 runs/hour from one address");
  });

  it("maps the concurrency-limit 429 the same way", () => {
    const message = friendlyMessage(429, { error: "rate_limited", detail: "busy, try again shortly" });
    expect(message).toBe("busy, try again shortly");
  });

  it("wraps an invalid_dataset detail with context", () => {
    const message = friendlyMessage(400, {
      error: "invalid_dataset",
      detail: "file name must end with .csv",
    });
    expect(message).toContain("file name must end with .csv");
    expect(message).toContain("couldn't be used");
  });

  it("wraps a request_too_large detail with context", () => {
    const message = friendlyMessage(413, {
      error: "request_too_large",
      detail: "body is 9999999 bytes, over the 5242880 byte limit",
    });
    expect(message).toContain("too large");
  });

  it("falls back to the raw detail for an unrecognized error code", () => {
    const message = friendlyMessage(500, { error: "something_new", detail: "oops" });
    expect(message).toBe("oops");
  });

  it("falls back to a generic message when there is no detail at all", () => {
    const message = friendlyMessage(500, { error: "something_new", detail: "" });
    expect(message).toBe("Request failed with status 500.");
  });
});

describe("ApiRequestError", () => {
  it("carries the status, code, and friendly message", () => {
    const error = new ApiRequestError(429, {
      error: "rate_limited",
      detail: "this demo's daily cap of 50 runs has been reached",
    });
    expect(error.status).toBe(429);
    expect(error.code).toBe("rate_limited");
    expect(error.message).toBe("this demo's daily cap of 50 runs has been reached");
  });
});
