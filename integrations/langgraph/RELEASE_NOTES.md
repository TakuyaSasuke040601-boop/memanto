# Release Notes for v0.1.0

This initial release introduces `langgraph-memanto`, a standalone package providing native tools to integrate [Memanto's](https://memanto.ai) persistent, cross-agent memory capabilities directly into your [LangGraph](https://langchain-ai.github.io/langgraph/) workflows.

## New Features

- **Persistent Memory Tools** (`langgraph_memanto.tools`)
  - Includes three highly optimized LangChain tools (`memanto_remember`, `memanto_recall`, and `memanto_answer`) ready to be bound to your LLMs and invoked by LangGraph agents.
- **Automatic Agent Initialization**
  - Tool execution dynamically handles the lifecycle of Memanto agents. The tools automatically create and activate the agent session behind the scenes the first time the LLM attempts to interact with memory, requiring zero setup code from the developer.
- **Serverless Architecture**
  - Wraps the Memanto SDK (`SdkClient`), allowing tools to communicate directly with the Moorcheh Cloud API without the need to run `memanto serve` locally.
- **Cross-Session Persistence**
  - Agents can store memories in one run and recall them in completely separate future runs or threads using a shared `agent_id`.
- **Semantic Type System**
  - The tools guide the LLM to categorize stored memories using 13 distinct semantic types (e.g., `fact`, `observation`, `decision`, `preference`), and the LLM determines and assigns confidence scores and custom tags.

## Improvements

- **Documentation & Examples**
  - Updated LangGraph integration documentation.
  - Revamped `examples/langgraph-memanto/` demonstrating basic tool usage, cross-session persistence, a custom state checkpointer (`MemantoMemory`), and a full multi-agent research pipeline.

## Full Changelog

Full Changelog: https://github.com/moorcheh-ai/memanto/commits/integrations/langgraph/v0.1.0
