/**
 * Markdown preview renderer tests.
 *
 * Run directly: node tests/markdown.test.mjs
 * The pytest wrapper runs this file when node is available.
 */
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const sourcePath = new URL("../abm_server/web/static/markdown.js", import.meta.url);
const directory = mkdtempSync(join(tmpdir(), "abm-markdown-"));
const modulePath = join(directory, "markdown.mjs");
writeFileSync(modulePath, readFileSync(sourcePath, "utf8"));
const { renderMarkdown } = await import(pathToFileURL(modulePath).href);

let failures = 0;
function check(name, condition, detail) {
  if (condition) {
    console.log(`  ok ${name}`);
  } else {
    failures += 1;
    console.error(`  FAIL ${name}${detail ? ` — ${detail}` : ""}`);
  }
}

const heading = renderMarkdown("# 标题\n\n正文");
check("heading", heading.includes("<h1>标题</h1>"), heading);
check("paragraph", heading.includes("<p>正文</p>"), heading);

const inline = renderMarkdown("**粗体** *斜体* ~~删除~~ `code`");
check("bold", inline.includes("<strong>粗体</strong>"), inline);
check("italic", inline.includes("<em>斜体</em>"), inline);
check("strike", inline.includes("<del>删除</del>"), inline);
check("inline code", inline.includes("<code>code</code>"), inline);

const rawHtml = renderMarkdown('<script>alert(1)</script>');
check("html escaped", !rawHtml.includes("<script>"), rawHtml);
check("html visible", rawHtml.includes("&lt;script&gt;"), rawHtml);

const unsafeLink = renderMarkdown("[点击](javascript:alert(1))");
check("javascript link stripped", !unsafeLink.includes("href=\"javascript"), unsafeLink);

const safeLink = renderMarkdown("[官网](https://example.com)");
check("https link", safeLink.includes('href="https://example.com"'), safeLink);
check("link rel", safeLink.includes('rel="noopener noreferrer"'), safeLink);

const image = renderMarkdown("![图](https://example.com/a.png)");
check("image", image.includes('<img src="https://example.com/a.png"'), image);

const list = renderMarkdown("- 一\n- 二\n\n1. 甲\n2. 乙");
check("unordered list", list.includes("<ul><li>一</li><li>二</li></ul>"), list);
check("ordered list", list.includes("<ol><li>甲</li><li>乙</li></ol>"), list);

const quote = renderMarkdown("> 引用");
check("blockquote", quote.includes("<blockquote>引用</blockquote>"), quote);

const fence = renderMarkdown("```js\nconst a = 1 < 2;\n```");
check("code fence", fence.includes("<pre><code class=\"language-js\">"), fence);
check("code escaped", fence.includes("1 &lt; 2"), fence);

const table = renderMarkdown("| A | B |\n| --- | --- |\n| 1 | 2 |");
check("table head", table.includes("<th>A</th>"), table);
check("table cell", table.includes("<td>1</td>"), table);

const breaks = renderMarkdown("第一行\n第二行");
check("line break", breaks.includes("第一行<br />第二行"), breaks);

const empty = renderMarkdown("");
check("empty", empty === "", empty);

if (failures) {
  console.error(`\n${failures} markdown check(s) failed`);
  process.exit(1);
}
console.log("\nmarkdown renderer tests passed");
