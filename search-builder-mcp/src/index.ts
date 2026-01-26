#!/usr/bin/env node
import express from "express";
import { z } from "zod";

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";

const API_BASE =
  (process.env.SEARCH_BUILDER_API_BASE || "http://127.0.0.1:8080").replace(/\/+$/, "");

const PORT = parseInt(process.env.PORT || "9000", 10);

type Json = Record<string, any>;

async function httpJson<T>(
  path: string,
  init: RequestInit & { timeoutMs?: number } = {}
): Promise<T> {
  const url = `${API_BASE}${path}`;

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), init.timeoutMs ?? 60_000);

  try {
    const resp = await fetch(url, {
      ...init,
      signal: controller.signal,
      headers: {
        "content-type": "application/json",
        ...(init.headers || {}),
      },
    });

    const text = await resp.text();
    let body: any = null;
    try {
      body = text ? JSON.parse(text) : null;
    } catch {
      body = text;
    }

    if (!resp.ok) {
      throw new Error(
        `HTTP ${resp.status} ${resp.statusText} from ${path}: ${JSON.stringify(body)}`
      );
    }
    return body as T;
  } finally {
    clearTimeout(timeout);
  }
}

// ------------------------------
// MCP Server + Tools
// ------------------------------
const server = new McpServer({
  name: "search-builder-mcp",
  version: "0.5.0",
});

server.tool(
  "health_check",
  {},
  { title: "health_check", readOnlyHint: true },
  async () => {
    const r = await httpJson<Json>("/health", { method: "GET", timeoutMs: 10_000 });
    return { content: [{ type: "text", text: JSON.stringify(r, null, 2) }] };
  }
);

server.tool(
  "start_ingest_s3",
  {
    type: z.enum(["BM25", "sparse", "dense", "hybrid"]).default("BM25"),
    bucket: z.string().min(1),
    prefix: z.string().default(""),
    index_name: z.string().min(1).default("docs"),
    delete_local: z.boolean().default(true),
    max_files: z.number().int().positive().optional(),
    aws_region: z.string().default("us-east-1"),
    topic: z.string().default("").describe("don't input it if you don't know"),
  },
  { title: "start_ingest_s3", destructiveHint: true, idempotentHint: false },
  async (args) => {
    const body: any = {
      bucket: args.bucket,
      prefix: args.prefix,
      index_name: args.index_name,
      delete_local: args.delete_local,
      max_files: args.max_files ?? null,
      aws_region: args.aws_region,
      type: args.type,
      topic: args.topic,
    };

    const r = await httpJson<{ task_id: string }>("/ingest_from_s3", {
      method: "POST",
      body: JSON.stringify(body),
      timeoutMs: 60_000,
    });

    return {
      content: [{ type: "text", text: JSON.stringify({ task_id: r.task_id }, null, 2) }],
    };
  }
);

server.tool(
  "start_ingest_local",
  {
    type: z.enum(["BM25", "sparse", "dense", "hybrid"]).default("BM25"),
    AbstractPath: z.string().min(1),
    index_name: z.string().min(1).default("docs"),
    topic: z.string().default("").describe("don't input it if you don't know"),
  },
  { title: "start_ingest_local", destructiveHint: true, idempotentHint: false },
  async (args) => {
    const body = {
      AbstractPath: args.AbstractPath,
      index_name: args.index_name,
      type: args.type,
      topic: args.topic,
    };

    const r = await httpJson<{ task_id: string }>("/ingest_from_local", {
      method: "POST",
      body: JSON.stringify(body),
      timeoutMs: 60_000,
    });

    return {
      content: [{ type: "text", text: JSON.stringify({ task_id: r.task_id }, null, 2) }],
    };
  }
);

server.tool(
  "get_manifest",
  {
    index_name: z.string().default(""),
    topic: z.string().default(""),
  },
  { title: "get_manifest", readOnlyHint: true },
  async (args) => {
    const r = await httpJson<Json>("/manifest", {
      method: "POST",
      body: JSON.stringify({
        index_name: args.index_name ?? "",
        topic: args.topic ?? "",
      }),
      timeoutMs: 30_000,
    });

    return { content: [{ type: "text", text: JSON.stringify(r, null, 2) }] };
  }
);

server.tool(
  "get_task",
  { task_id: z.string().min(1) },
  { title: "get_task", readOnlyHint: true },
  async (args) => {
    const r = await httpJson<Json>(`/tasks/${encodeURIComponent(args.task_id)}`, {
      method: "GET",
      timeoutMs: 10_000,
    });
    return { content: [{ type: "text", text: JSON.stringify(r, null, 2) }] };
  }
);

server.tool(
  "wait_task",
  {
    task_id: z.string().min(1),
    timeout_s: z.number().int().positive().default(600),
    poll_s: z.number().int().positive().default(2),
  },
  { title: "wait_task", readOnlyHint: true },
  async (args) => {
    const deadline = Date.now() + args.timeout_s * 1000;

    while (true) {
      const t = await httpJson<Json>(`/tasks/${encodeURIComponent(args.task_id)}`, {
        method: "GET",
        timeoutMs: 10_000,
      });

      const status = String(t?.status || "").toUpperCase();
      if (status === "SUCCEEDED" || status === "FAILED") {
        return { content: [{ type: "text", text: JSON.stringify(t, null, 2) }] };
      }

      if (Date.now() > deadline) {
        return {
          content: [
            {
              type: "text",
              text: JSON.stringify(
                { task_id: args.task_id, status: t?.status ?? "UNKNOWN", error: "TIMEOUT" },
                null,
                2
              ),
            },
          ],
        };
      }

      await new Promise((r) => setTimeout(r, args.poll_s * 1000));
    }
  }
);

server.tool(
  "search",
  {
    index: z.string().min(1),
    query: z.string().min(1),
    size: z.number().int().positive().default(5),
    mode: z.enum(["BM25", "dense", "sparse"]).default("BM25"),
  },
  { title: "search", readOnlyHint: true },
  async (args) => {
    const r = await httpJson<Json>("/search", {
      method: "POST",
      body: JSON.stringify({
        index: args.index,
        query: args.query,
        size: args.size,
        mode: args.mode,
      }),
      timeoutMs: 60_000,
    });

    return { content: [{ type: "text", text: JSON.stringify(r, null, 2) }] };
  }
);

// ------------------------------
// Streamable HTTP (Remote MCP)
// ------------------------------
async function main() {
  // createMcpExpressApp() 给了安全默认配置（可留着）
  const app = express();
  app.use(express.json({ limit: "5mb" }));

  const transport = new StreamableHTTPServerTransport({ sessionIdGenerator: undefined });
  await server.connect(transport);

  app.get("/health", (_req, res) => {
    res.json({
      status: "ok",
      service: "search-builder-mcp",
      version: "0.5.0",
      api_base: API_BASE,
      mcp_endpoint: "/mcp",
      transport: "streamable-http",
    });
  });

  app.post("/mcp", async (req, res) => {
    try {
      await transport.handleRequest(req, res, req.body);
    } catch (error) {
      console.error("MCP request error:", error);
      if (!res.headersSent) {
        res.status(500).json({
          error: "Internal server error",
          message: error instanceof Error ? error.message : String(error),
        });
      }
    }
  });

  // ✅ Docker 里必须 0.0.0.0
  app.listen(PORT, "0.0.0.0", () => {
    console.log(`🚀 Search Builder MCP Server running on :${PORT}`);
    console.log(`📡 MCP Endpoint: http://0.0.0.0:${PORT}/mcp`);
    console.log(`🔗 Backend API: ${API_BASE}`);
  });
}

main().catch((e) => {
  console.error("MCP server failed:", e);
  process.exit(1);
});
