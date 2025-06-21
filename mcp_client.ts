// mcp-client.ts
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { HTTPTransport } from "@modelcontextprotocol/sdk/client/http.js";
import { streamText, tool } from "ai";
import { openai } from "@ai-sdk/openai";
import { z } from "zod";

// MCP Client 설정
class MCPClient {
  private client: Client;
  private transport: HTTPTransport;

  constructor(serverUrl: string) {
    // HTTP Transport 생성
    this.transport = new HTTPTransport(new URL(serverUrl));
    this.client = new Client(
      {
        name: "mcp-ai-client",
        version: "1.0.0",
      },
      {
        capabilities: {
          tools: {},
        },
      }
    );
  }

  async connect() {
    await this.client.connect(this.transport);
  }

  async disconnect() {
    await this.client.close();
  }

  // MCP 도구들을 가져와서 AI SDK 도구 형식으로 변환
  async getToolsForAI() {
    const toolsResult = await this.client.listTools();
    const tools: Record<string, any> = {};

    for (const mcpTool of toolsResult.tools) {
      tools[mcpTool.name] = tool({
        description: mcpTool.description || "",
        parameters: mcpTool.inputSchema || z.object({}),
        execute: async (args) => {
          const result = await this.client.callTool({
            name: mcpTool.name,
            arguments: args,
          });
          return result.content;
        },
      });
    }

    return tools;
  }

  // 리소스 목록 가져오기
  async getResources() {
    return await this.client.listResources();
  }

  // 특정 리소스 읽기
  async readResource(uri: string) {
    return await this.client.readResource({ uri });
  }
}

// AI SDK와 MCP 통합 예제
export async function createStreamingChat(mcpServerUrl: string) {
  const mcpClient = new MCPClient(mcpServerUrl);

  try {
    await mcpClient.connect();
    const tools = await mcpClient.getToolsForAI();

    return async function* streamChat(messages: any[]) {
      const result = await streamText({
        model: openai("gpt-4-turbo"),
        messages,
        tools,
        maxToolRoundtrips: 5,
      });

      // 스트림 처리
      for await (const delta of result.textStream) {
        yield {
          type: "text",
          content: delta,
        };
      }

      // 도구 호출 결과 처리
      for await (const step of result.steps) {
        if (step.toolCalls) {
          for (const toolCall of step.toolCalls) {
            yield {
              type: "tool_call",
              toolName: toolCall.toolName,
              args: toolCall.args,
              result: toolCall.result,
            };
          }
        }
      }
    };
  } catch (error) {
    await mcpClient.disconnect();
    throw error;
  }
}

// 사용 예제
export async function exampleUsage() {
  const streamChat = await createStreamingChat("http://localhost:3001/mcp");

  const messages = [
    {
      role: "user",
      content: "MCP 서버에서 사용 가능한 도구들을 사용해서 파일을 읽어주세요.",
    },
  ];

  for await (const chunk of streamChat(messages)) {
    if (chunk.type === "text") {
      console.log("Text:", chunk.content);
    } else if (chunk.type === "tool_call") {
      console.log("Tool Call:", chunk.toolName, chunk.result);
    }
  }
}

// Express.js 서버에서 사용하는 예제
import express from "express";

const app = express();
app.use(express.json());

app.post("/chat/stream", async (req, res) => {
  const { messages, mcpServerUrl } = req.body;

  res.writeHead(200, {
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache",
    Connection: "keep-alive",
    "Access-Control-Allow-Origin": "*",
  });

  try {
    const streamChat = await createStreamingChat(mcpServerUrl);

    for await (const chunk of streamChat(messages)) {
      res.write(`data: ${JSON.stringify(chunk)}\n\n`);
    }
  } catch (error) {
    res.write(
      `data: ${JSON.stringify({ type: "error", error: error.message })}\n\n`
    );
  } finally {
    res.write("data: [DONE]\n\n");
    res.end();
  }
});

// React에서 사용하는 클라이언트 예제
export function useMCPChat(mcpServerUrl: string) {
  const [messages, setMessages] = useState([]);
  const [isLoading, setIsLoading] = useState(false);

  const sendMessage = async (newMessage: string) => {
    setIsLoading(true);
    const updatedMessages = [
      ...messages,
      { role: "user", content: newMessage },
    ];
    setMessages(updatedMessages);

    try {
      const response = await fetch("/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          messages: updatedMessages,
          mcpServerUrl,
        }),
      });

      const reader = response.body?.getReader();
      if (!reader) throw new Error("No reader available");

      let assistantMessage = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = new TextDecoder().decode(value);
        const lines = chunk.split("\n");

        for (const line of lines) {
          if (line.startsWith("data: ") && line !== "data: [DONE]") {
            const data = JSON.parse(line.slice(6));

            if (data.type === "text") {
              assistantMessage += data.content;
              setMessages((prev) => [
                ...prev.slice(0, -1),
                { role: "assistant", content: assistantMessage },
              ]);
            } else if (data.type === "tool_call") {
              console.log("Tool used:", data.toolName, data.result);
            }
          }
        }
      }
    } catch (error) {
      console.error("Chat error:", error);
    } finally {
      setIsLoading(false);
    }
  };

  return { messages, sendMessage, isLoading };
}

// MCP 서버와의 실시간 연결 관리
export class MCPConnectionManager {
  private connections = new Map<string, MCPClient>();

  async getConnection(serverUrl: string): Promise<MCPClient> {
    if (!this.connections.has(serverUrl)) {
      const client = new MCPClient(serverUrl);
      await client.connect();
      this.connections.set(serverUrl, client);
    }
    return this.connections.get(serverUrl)!;
  }

  async closeAll() {
    for (const [url, client] of this.connections) {
      await client.disconnect();
    }
    this.connections.clear();
  }
}
