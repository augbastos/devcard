import { SELF } from "cloudflare:test";
import { beforeEach, describe, expect, it } from "vitest";
import { resetDb, ev, ingestRequest } from "./helpers";

async function ingest(events: ReturnType<typeof ev>[]): Promise<void> {
  const res = await SELF.fetch(
    ingestRequest({ source_id: "metrics", events, repo_count: 5 })
  );
  expect(res.status).toBe(200);
}

const card = async (query = "") =>
  (await SELF.fetch(`https://card.example/svg${query}`)).text();

describe("capture-mode semantics", () => {
  beforeEach(async () => {
    await resetDb();
  });

  it("counts agent tool calls as code edits on a claude-mode card", async () => {
    await ingest([
      ev({ id: 1, event_type: "edit" }),
      ev({ id: 2, event_type: "edit" }),
      ev({ id: 3, event_type: "write" }),
      ev({ id: 4, event_type: "commit", language: null, lines_added: 0 }),
    ]);
    const svg = await card();
    expect(svg).toContain(">3</tspan>");
    expect(svg).toContain("code edits");
    expect(svg).toContain("commits");
  });

  it("does not print a code-edits number for a git-mode card", async () => {
    // Git-mode rows are per-commit, per-language aggregates. Showing "2 code
    // edits" for two commits touching two languages would be a number the
    // label does not describe — and one a viewer would compare against a
    // claude-mode card where it counts something else entirely.
    await ingest([
      ev({ id: 1, event_type: "diff", language: "Python" }),
      ev({ id: 2, event_type: "diff", language: "TypeScript" }),
      ev({ id: 3, event_type: "commit", language: null, lines_added: 0 }),
    ]);
    const svg = await card();
    expect(svg).not.toContain("code edits");
    expect(svg).toContain("commits");
  });

  it("still counts git-mode lines, languages and days", async () => {
    // Dropping the misleading label must not drop the honest data with it.
    await ingest([
      ev({ id: 1, event_type: "diff", language: "Python", lines_added: 40 }),
      ev({ id: 2, event_type: "diff", language: "Rust", lines_added: 10 }),
      ev({ id: 3, event_type: "commit", language: null, lines_added: 0 }),
    ]);
    const svg = await card();
    expect(svg).toContain("50");
    expect(svg).toContain("Python");
    expect(svg).toContain("Rust");
    expect(svg).toContain("lines written");
  });

  it("shows agent edits on a card that has both kinds of history", async () => {
    // A machine that switched modes. "code edits" then counts only the agent
    // calls, which is exactly what the label claims.
    await ingest([
      ev({ id: 1, event_type: "edit" }),
      ev({ id: 2, event_type: "diff" }),
      ev({ id: 3, event_type: "diff" }),
      ev({ id: 4, event_type: "commit", language: null, lines_added: 0 }),
    ]);
    const svg = await card();
    expect(svg).toContain("code edits");
    expect(svg).toContain(">1</tspan>");
  });

  it("applies the same rule to the half layout", async () => {
    await ingest([
      ev({ id: 1, event_type: "diff" }),
      ev({ id: 2, event_type: "commit", language: null, lines_added: 0 }),
    ]);
    const gitCard = await card("?layout=half");
    expect(gitCard).not.toContain("code edits");
    expect(gitCard).toContain("commits");

    await resetDb();
    await ingest([
      ev({ id: 3, event_type: "edit" }),
      ev({ id: 4, event_type: "commit", language: null, lines_added: 0 }),
    ]);
    const claudeCard = await card("?layout=half");
    expect(claudeCard).toContain("code edits");
  });

  it("translates the labels it does show", async () => {
    await ingest([
      ev({ id: 1, event_type: "edit" }),
      ev({ id: 2, event_type: "commit", language: null, lines_added: 0 }),
    ]);
    expect(await card("?lang=pt")).toContain("edições de código");
    expect(await card("?lang=es")).toContain("ediciones de código");
  });
});
