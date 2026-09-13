import { describe, expect, it } from "vitest";
import { parseSseChunk } from "./agentApi";

describe("parseSseChunk", () => {
  it("parses progress events", () => {
    expect(parseSseChunk('data: {"type":"progress","step":"校验SQL","status":"running"}')).toEqual({
      type: "progress",
      step: "校验SQL",
      status: "running",
    });
  });

  it("parses result events", () => {
    expect(parseSseChunk('data: {"type":"result","data":[{"gmv":41099.5}]}')).toEqual({
      type: "result",
      data: [{ gmv: 41099.5 }],
    });
  });

  it("parses error events", () => {
    expect(parseSseChunk('data: {"type":"error","message":"模拟失败"}')).toEqual({
      type: "error",
      message: "模拟失败",
    });
  });

  it("joins multiline data fields", () => {
    expect(parseSseChunk('data: {"type":"error",\ndata: "message":"断行"}')).toEqual({
      type: "error",
      message: "断行",
    });
  });

  it("returns null for empty chunks", () => {
    expect(parseSseChunk("")).toBeNull();
    expect(parseSseChunk(": keep-alive")).toBeNull();
  });

  it("wraps malformed json as error", () => {
    expect(parseSseChunk("data: {bad")).toEqual({
      type: "error",
      message: "无法解析后端事件：{bad",
    });
  });
});
