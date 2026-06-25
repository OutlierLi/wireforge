import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { once } from "node:events";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { createInterface } from "node:readline/promises";
import { stdin, stdout } from "node:process";

const SCHEMA = "protocol-tui.v1";
const HISTORY_LIMIT = 200;
const HISTORY_FILE = join(process.cwd(), ".wireforge_history");

type Status =
  | "success"
  | "need_input"
  | "need_disambiguation"
  | "invalid_argument"
  | "no_route"
  | "execution_error"
  | "session_closed";

type WireResponse = {
  schema: string;
  status: Status;
  data?: Record<string, unknown>;
  input_schema?: InputField[];
  candidates?: Candidate[];
  interaction_id?: string;
  key?: string;
  hint?: string;
  error?: string;
  detail?: Record<string, unknown>;
  path?: string;
};

type InputField = {
  key?: string;
  name?: string;
  type?: string;
  desc?: string;
  description?: string;
  examples?: unknown[];
};

type Candidate = {
  value: string;
  label?: string;
};

type Pending = {
  resolve: (response: WireResponse) => void;
  reject: (error: Error) => void;
};

type SemanticToken =
  | "success"
  | "warning"
  | "error"
  | "command"
  | "field_name"
  | "field_value"
  | "frame_byte"
  | "route_selected"
  | "route_candidate"
  | "text"
  | "subtle"
  | "accent"
  | "command_bar"
  | "result_title";

type OutputLine = {
  text: string;
  token: SemanticToken;
};

type FormState = {
  interactionId: string;
  fields: InputField[];
  index: number;
  args: Record<string, string>;
};

type ConnectionItem = {
  name: string;
  state: string;
  port: string;
  baudrate: string;
  lastError: string;
};

type InputKey = {
  name?: string;
  ctrl?: boolean;
  meta?: boolean;
  sequence?: string;
};

type SelectionPoint = {
  row: number;
  col: number;
};

type Selection = {
  start: SelectionPoint;
  end: SelectionPoint;
  active: boolean;
  dragged: boolean;
};

const reset = "\x1b[0m";
const color: Record<SemanticToken, string> = {
  success: "\x1b[32m",
  warning: "\x1b[33m",
  error: "\x1b[31m",
  command: "\x1b[36m",
  field_name: "\x1b[34m",
  field_value: "\x1b[37m",
  frame_byte: "\x1b[32m",
  route_selected: "\x1b[35m",
  route_candidate: "\x1b[36m",
  text: "\x1b[37m",
  subtle: "\x1b[90m",
  accent: "\x1b[36m",
  command_bar: "\x1b[1;37m\x1b[48;5;238m",
  result_title: "\x1b[1;37m",
};

function paint(text: string, token: SemanticToken = "text"): string {
  return `${color[token]}${text}${reset}`;
}

class NdjsonBackend {
  private proc: ChildProcessWithoutNullStreams;
  private pending: Pending[] = [];
  private buffer = "";
  private onDiagnostic: (text: string) => void;

  constructor(onDiagnostic: (text: string) => void) {
    this.onDiagnostic = onDiagnostic;
    this.proc = spawn("python3", ["-m", "console.ndjson"], {
      stdio: ["pipe", "pipe", "pipe"],
      cwd: process.cwd(),
    });
    this.proc.stdout.setEncoding("utf8");
    this.proc.stderr.setEncoding("utf8");
    this.proc.stdout.on("data", (chunk: string) => this.onStdout(chunk));
    this.proc.stderr.on("data", (chunk: string) => this.onDiagnostic(chunk.trimEnd()));
    this.proc.on("exit", (code) => {
      const error = new Error(`Python runtime exited with code ${code ?? "unknown"}`);
      for (const item of this.pending.splice(0)) item.reject(error);
    });
  }

  async request(message: Record<string, unknown>): Promise<WireResponse> {
    if (!this.proc.stdin.writable) {
      throw new Error("Python runtime is not writable");
    }
    const payload = { schema: SCHEMA, ...message };
    const promise = new Promise<WireResponse>((resolve, reject) => {
      this.pending.push({ resolve, reject });
    });
    this.proc.stdin.write(`${JSON.stringify(payload)}\n`);
    return promise;
  }

  close(): void {
    this.proc.stdin.destroy();
    this.proc.stdout.destroy();
    this.proc.stderr.destroy();
    if (!this.proc.killed) this.proc.kill("SIGKILL");
  }

  private onStdout(chunk: string): void {
    this.buffer += chunk;
    let newline = this.buffer.indexOf("\n");
    while (newline >= 0) {
      const line = this.buffer.slice(0, newline).trim();
      this.buffer = this.buffer.slice(newline + 1);
      if (line) this.resolveLine(line);
      newline = this.buffer.indexOf("\n");
    }
  }

  private resolveLine(line: string): void {
    const item = this.pending.shift();
    if (!item) return;
    try {
      item.resolve(JSON.parse(line) as WireResponse);
    } catch (error) {
      item.reject(error instanceof Error ? error : new Error(String(error)));
    }
  }
}

class Screen {
  private lines: OutputLine[] = [];
  private lastCopyText = "";
  private input = "";
  private cursor = 0;
  private prompt = ">";
  private status = "READY";
  private activeConnection = "default";
  private connections: ConnectionItem[] = [];
  private scrollOffset = 0;
  private visibleOutputRows: string[] = [];
  private outputTopRow = 1;
  private outputRightCol = Infinity;
  private selection: Selection | undefined;

  setInput(value: string, cursor: number): void {
    this.input = value;
    this.cursor = Math.max(0, Math.min(cursor, Array.from(value).length));
  }

  setPrompt(prompt: string): void {
    this.prompt = prompt;
  }

  setStatus(status: string): void {
    this.status = status;
  }

  setActiveConnection(name: string): void {
    if (name) this.activeConnection = name;
  }

  clear(): void {
    this.lines = [];
    this.lastCopyText = "";
    this.scrollOffset = 0;
    this.visibleOutputRows = [];
    this.selection = undefined;
  }

  copyText(): string {
    return this.lastCopyText;
  }

  add(text: string, token: SemanticToken = "text"): void {
    for (const line of text.split(/\r?\n/)) {
      this.lines.push({ text: line, token });
    }
    this.lines = this.lines.slice(-1000);
  }

  scrollBy(delta: number): void {
    if (this.lines.length === 0) {
      this.scrollOffset = 0;
      return;
    }
    this.scrollOffset = Math.max(0, this.scrollOffset + delta);
  }

  scrollToBottom(): void {
    this.scrollOffset = 0;
  }

  addCommand(text: string): void {
    if (this.lines.length > 0) this.add("", "text");
    this.add(`› ${text}`, "command_bar");
    this.add("", "text");
  }

  renderResponse(response: WireResponse): void {
    if (response.status === "success") {
      this.renderSuccess(response.data ?? {});
      this.add("", "text");
      return;
    }
    if (response.status === "need_input") {
      this.add("● need input", "result_title");
      this.add("└  fill required fields", "subtle");
      for (const field of response.input_schema ?? []) {
        const key = field.key ?? field.name ?? "";
        const type = field.type ?? "str";
        const desc = field.desc ?? field.description ?? "";
        this.add(`   --${key}: ${type}${desc ? `  ${desc}` : ""}`, "field_name");
      }
      if (response.hint) this.add(response.hint, "subtle");
      this.add("", "text");
      return;
    }
    if (response.status === "need_disambiguation") {
      this.add(`● need disambiguation ${response.key ?? ""}`.trimEnd(), "result_title");
      for (const candidate of response.candidates ?? []) {
        this.add(`└  ${candidate.label ?? candidate.value}`, "route_candidate");
      }
      this.add("", "text");
      return;
    }
    if (response.status === "session_closed") {
      this.add(`● session closed ${response.interaction_id ?? ""}`.trimEnd(), "subtle");
      this.add("", "text");
      return;
    }
    this.add(`● ${response.status}`, "error");
    this.add(`└  ${response.error ?? response.status}`, "error");
    if (response.path) this.add(`   ${response.path}`, "route_selected");
    this.add("", "text");
  }

  draw(): void {
    const cols = Math.max(stdout.columns || 100, 60);
    const rows = Math.max(stdout.rows || 30, 18);
    const sideWidth = cols >= 100 ? Math.min(34, Math.max(28, Math.floor(cols * 0.22))) : 0;
    const mainCols = sideWidth > 0 ? cols - sideWidth - 1 : cols;
    const chromeHeight = 4;
    const outputHeight = rows - chromeHeight;

    const out: string[] = [];
    out.push("\x1b[?25l\x1b[H");
    this.outputTopRow = 1;
    this.outputRightCol = mainCols;
    const outputLines: string[] = [];

    if (this.lines.length === 0) {
      const welcome = this.welcomeLines(mainCols, outputHeight);
      this.visibleOutputRows = welcome.map((line) => stripAnsi(line));
      outputLines.push(...welcome);
    } else {
      const wrapped = this.wrapVisibleLines(mainCols - 2);
      const maxOffset = Math.max(wrapped.length - outputHeight, 0);
      this.scrollOffset = Math.min(this.scrollOffset, maxOffset);
      const end = Math.max(wrapped.length - this.scrollOffset, 0);
      const start = Math.max(end - outputHeight, 0);
      const visible = wrapped.slice(start, end);
      this.visibleOutputRows = [];
      for (let i = 0; i < outputHeight; i += 1) {
        const line = visible[i];
        if (line) {
          this.visibleOutputRows.push(this.outputPlainLine(line, mainCols));
          outputLines.push(this.renderOutputLine(line, mainCols, this.outputTopRow + i));
        } else {
          this.visibleOutputRows.push("");
          outputLines.push(" ".repeat(mainCols));
        }
      }
    }
    out.push(...this.composeMainAndSide(outputLines, mainCols, sideWidth, outputHeight));
    out.push(this.statusLine(mainCols) + (sideWidth > 0 ? paint("│", "subtle") + " ".repeat(sideWidth) : ""));
    out.push(this.accentLine(mainCols) + (sideWidth > 0 ? paint("│", "subtle") + " ".repeat(sideWidth) : ""));
    out.push(this.inputLine(mainCols) + (sideWidth > 0 ? paint("│", "subtle") + " ".repeat(sideWidth) : ""));
    out.push(this.accentLine(mainCols) + (sideWidth > 0 ? paint("│", "subtle") + " ".repeat(sideWidth) : ""));
    out.push(this.cursorMove(rows, cols));
    stdout.write(out.join("\n"));
  }

  private renderSuccess(data: Record<string, unknown>): void {
    const copyLines: string[] = [];
    if (typeof data.active === "string") this.setActiveConnection(data.active);
    else if (typeof data.name === "string" && data.status === "active") this.setActiveConnection(data.name);
    this.ingestConnectionData(data);
    this.add("● success", "result_title");
    if (Array.isArray(data.connections)) {
      this.renderConnections(data, copyLines);
    }
    if (typeof data.path === "string") {
      this.add(`└  path: ${data.path}`, "route_selected");
      copyLines.push(data.path);
    }
    if (typeof data.frame === "string") {
      this.add(`   frame: ${data.frame}`, "frame_byte");
      copyLines.push(data.frame);
    }
    for (const [key, value] of Object.entries(data)) {
      if (key === "connections") continue;
      if (key === "active" && Array.isArray(data.connections)) continue;
      if (key === "path" || key === "frame") continue;
      this.renderValue(key, value, 0, copyLines);
    }
    this.lastCopyText = copyLines.join("\n");
  }

  private ingestConnectionData(data: Record<string, unknown>): void {
    if (Array.isArray(data.connections)) {
      this.connections = this.parseConnections(data.connections);
      return;
    }
    if (typeof data.name !== "string" && typeof data.id !== "string") return;
    const name = String(data.name ?? data.id);
    const state = String(data.status ?? "connected");
    const existing = this.connections.findIndex((item) => item.name === name);
    const prev = existing >= 0 ? this.connections[existing] : null;
    // 只覆盖响应中实际存在的字段，避免 send 等操作返回的 port/baudrate 为
    // 空字符串时把 connect 时记录的有效值覆盖掉。
    const next: ConnectionItem = {
      name,
      state,
      port: data.port !== undefined ? String(data.port) : (prev?.port ?? ""),
      baudrate: data.baudrate !== undefined ? String(data.baudrate) : (prev?.baudrate ?? ""),
      lastError: "",
    };
    if (state === "closed") {
      if (prev) this.connections[existing] = { ...prev, state: "disconnected" };
      return;
    }
    if (prev) this.connections[existing] = { ...prev, ...next };
    else this.connections.push(next);
  }

  private parseConnections(items: unknown[]): ConnectionItem[] {
    const parsed: ConnectionItem[] = [];
    for (const item of items) {
      if (!item || typeof item !== "object") continue;
      const conn = item as Record<string, unknown>;
      parsed.push({
        name: String(conn.name ?? conn.id ?? ""),
        state: String(conn.state ?? "unknown"),
        port: String(conn.port ?? ""),
        baudrate: String(conn.baudrate ?? ""),
        lastError: conn.last_error ? String(conn.last_error) : "",
      });
    }
    return parsed.filter((item) => item.name);
  }

  private renderConnections(data: Record<string, unknown>, copyLines: string[]): void {
    const active = typeof data.active === "string" ? data.active : this.activeConnection;
    this.setActiveConnection(active);
    this.add(`   active: ${active}`, "field_name");
    copyLines.push(`active: ${active}`);
    this.add("   connections:", "field_name");
    copyLines.push("connections:");
    for (const item of data.connections as unknown[]) {
      if (!item || typeof item !== "object") continue;
      const conn = item as Record<string, unknown>;
      const name = String(conn.name ?? conn.id ?? "");
      const marker = name === active ? "*" : " ";
      const state = String(conn.state ?? "unknown");
      const port = String(conn.port ?? "");
      const baudrate = String(conn.baudrate ?? "");
      const err = conn.last_error ? `  ${String(conn.last_error)}` : "";
      const line = `${marker} ${name}  ${state}  ${port}${baudrate ? `  ${baudrate}` : ""}${err}`;
      this.add(`   ${line}`, state === "connected" ? "success" : "warning");
      copyLines.push(line);
    }
  }

  private renderValue(key: string, value: unknown, depth: number, copyLines: string[]): void {
    const indent = "  ".repeat(depth);
    if (Array.isArray(value)) {
      this.add(`   ${indent}${key}:`, "field_name");
      copyLines.push(`${indent}${key}:`);
      for (const item of value) this.renderValue("-", item, depth + 1, copyLines);
      return;
    }
    if (value && typeof value === "object") {
      this.add(`   ${indent}${key}:`, "field_name");
      copyLines.push(`${indent}${key}:`);
      for (const [childKey, childValue] of Object.entries(value as Record<string, unknown>)) {
        this.renderValue(childKey, childValue, depth + 1, copyLines);
      }
      return;
    }
    const line = `${indent}${key}: ${String(value)}`;
    this.add(`   ${line}`, key === "protocol" ? "field_name" : "field_value");
    copyLines.push(line);
  }

  beginSelection(screenRow: number, screenCol: number): boolean {
    if (screenCol > this.outputRightCol) return false;
    const row = this.outputIndexForScreenRow(screenRow);
    if (row < 0 || row >= this.visibleOutputRows.length) return false;
    const col = this.clampSelectionCol(row, screenCol - 1);
    this.selection = { start: { row, col }, end: { row, col }, active: true, dragged: false };
    this.lastCopyText = "";
    return true;
  }

  updateSelection(screenRow: number, screenCol: number): boolean {
    if (!this.selection || !this.selection.active) return false;
    const row = Math.max(0, Math.min(this.outputIndexForScreenRow(screenRow), this.visibleOutputRows.length - 1));
    const col = this.clampSelectionCol(row, Math.min(screenCol, this.outputRightCol) - 1);
    if (row !== this.selection.start.row || col !== this.selection.start.col) this.selection.dragged = true;
    this.selection.end = { row, col };
    this.updateCopyFromSelection();
    return true;
  }

  endSelection(screenRow: number, screenCol: number): boolean {
    if (!this.selection || !this.selection.active) return false;
    this.updateSelection(screenRow, screenCol);
    if (!this.selection.dragged || !this.lastCopyText) {
      this.selection = undefined;
      this.lastCopyText = "";
      return true;
    }
    this.selection.active = false;
    return true;
  }

  clearSelection(): boolean {
    if (!this.selection) return false;
    this.selection = undefined;
    this.lastCopyText = "";
    return true;
  }

  private outputIndexForScreenRow(screenRow: number): number {
    return screenRow - this.outputTopRow;
  }

  private selectionRangeForScreenRow(screenRow: number): { start: number; end: number } | undefined {
    if (!this.selection) return undefined;
    const row = this.outputIndexForScreenRow(screenRow);
    const { start, end } = this.normalizedSelection();
    if (row < start.row || row > end.row) return undefined;
    const lineWidth = visibleLength(this.visibleOutputRows[row] ?? "");
    if (start.row === end.row) return { start: start.col, end: end.col };
    if (row === start.row) return { start: start.col, end: lineWidth };
    if (row === end.row) return { start: 0, end: end.col };
    return { start: 0, end: lineWidth };
  }

  private updateCopyFromSelection(): void {
    if (!this.selection) return;
    const { start, end } = this.normalizedSelection();
    const selected: string[] = [];
    for (let row = start.row; row <= end.row; row += 1) {
      const line = this.visibleOutputRows[row] ?? "";
      const lineWidth = visibleLength(line);
      let from = 0;
      let to = lineWidth;
      if (start.row === end.row) {
        from = start.col;
        to = end.col;
      } else if (row === start.row) {
        from = start.col;
      } else if (row === end.row) {
        to = end.col;
      }
      selected.push(sliceCells(line, from, to).trimEnd());
    }
    this.lastCopyText = selected.join("\n").trimEnd();
  }

  private normalizedSelection(): { start: SelectionPoint; end: SelectionPoint } {
    const selection = this.selection;
    if (!selection) return { start: { row: 0, col: 0 }, end: { row: 0, col: 0 } };
    const a = selection.start;
    const b = selection.end;
    if (a.row < b.row || (a.row === b.row && a.col <= b.col)) return { start: a, end: b };
    return { start: b, end: a };
  }

  private clampSelectionCol(row: number, col: number): number {
    const width = visibleLength(this.visibleOutputRows[row] ?? "");
    return Math.max(0, Math.min(col, width));
  }

  private outputPlainLine(line: OutputLine, cols: number): string {
    if (line.token === "command_bar") return pad(line.text, cols);
    return ` ${pad(line.text, cols - 2)} `;
  }

  private renderOutputLine(line: OutputLine, cols: number, screenRow: number): string {
    const range = this.selectionRangeForScreenRow(screenRow);
    if (line.token === "command_bar") {
      return this.renderSelectablePlain(this.outputPlainLine(line, cols), "command_bar", range);
    }
    return this.renderSelectablePlain(this.outputPlainLine(line, cols), line.token, range);
  }

  private renderSelectablePlain(text: string, token: SemanticToken, range?: { start: number; end: number }): string {
    if (!range || range.start === range.end) return paint(text, token);
    const before = sliceCells(text, 0, range.start);
    const selected = sliceCells(text, range.start, range.end);
    const after = sliceCells(text, range.end, visibleLength(text));
    return `${paint(before, token)}\x1b[7m${selected}\x1b[0m${paint(after, token)}`;
  }

  private statusLine(cols: number): string {
    const scroll = this.scrollOffset > 0 ? `  scroll +${this.scrollOffset}` : "";
    const status = `${this.status.toLowerCase()}${scroll}  wheel/PgUp/PgDn output  drag select copies  ↑↓ history  Ctrl+L clear  Ctrl+Q exit`;
    return paint(status.padStart(cols), "subtle");
  }

  private composeMainAndSide(outputLines: string[], mainCols: number, sideWidth: number, height: number): string[] {
    if (sideWidth <= 0) return outputLines;
    const side = this.connectionSidePanel(sideWidth, height);
    return outputLines.map((line, index) => `${line}${paint("│", "subtle")}${side[index] ?? " ".repeat(sideWidth)}`);
  }

  private connectionSidePanel(width: number, height: number): string[] {
    const items = this.connections.length > 0
      ? this.connections
      : [{ name: this.activeConnection, state: "unknown", port: "", baudrate: "", lastError: "" }];
    const visibleItems = items.some((item) => item.name === this.activeConnection)
      ? items
      : [{ name: this.activeConnection, state: "unknown", port: "", baudrate: "", lastError: "" }, ...items];
    const lines: string[] = [];
    lines.push(" ".repeat(width));
    lines.push(paint(pad(" Serial", width), "result_title"));
    lines.push(paint(pad(" *  name       port", width), "subtle"));
    for (const item of visibleItems) {
      const active = item.name === this.activeConnection;
      const marker = active ? "*" : " ";
      const name = fit(item.name, 10);
      const port = fit(item.port || "-", Math.max(width - 14, 4));
      lines.push(paint(pad(` ${marker} ${name} ${port}`, width), "text"));
      if (lines.length >= height) break;
    }
    while (lines.length < height) lines.push(" ".repeat(width));
    return lines;
  }

  private welcomeLines(cols: number, height: number): string[] {
    const lines = Array.from({ length: height }, () => " ".repeat(cols));
    const logo = [
      "██╗    ██╗██╗██████╗ ███████╗███████╗ ██████╗ ██████╗  ██████╗ ███████╗",
      "██║    ██║██║██╔══██╗██╔════╝██╔════╝██╔═══██╗██╔══██╗██╔════╝ ██╔════╝",
      "██║ █╗ ██║██║██████╔╝█████╗  █████╗  ██║   ██║██████╔╝██║  ███╗█████╗  ",
      "██║███╗██║██║██╔══██╗██╔══╝  ██╔══╝  ██║   ██║██╔══██╗██║   ██║██╔══╝  ",
      "╚███╔███╔╝██║██║  ██║███████╗██║     ╚██████╔╝██║  ██║╚██████╔╝███████╗",
      " ╚══╝╚══╝ ╚═╝╚═╝  ╚═╝╚══════╝╚═╝      ╚═════╝ ╚═╝  ╚═╝ ╚═════╝ ╚══════╝",
    ];
    const promptBox = [
      'Ask anything...  "/build --protocol=dlt645 --func=0x11 --di=00010000"',
      "Runtime · Python command-runtime over protocol-tui.v1",
    ];
    const tip = "Tip  /help commands   /connect opens transport   Ctrl+Q exits";
    const start = Math.max(1, Math.floor(height / 2) - 7);

    for (let i = 0; i < logo.length && start + i < height; i += 1) {
      lines[start + i] = center(logo[i], cols, i < 2 ? "subtle" : "text");
    }

    const boxWidth = Math.max(24, Math.min(cols - 4, Math.max(72, Math.min(100, cols - 16))));
    const boxStart = start + logo.length + 2;
    if (boxStart + 2 < height) {
      const leftPad = " ".repeat(Math.max(Math.floor((cols - boxWidth) / 2), 0));
      lines[boxStart] = `${leftPad}${paint("▌", "accent")}${paint(" ".repeat(boxWidth - 1), "subtle")}${" ".repeat(Math.max(cols - leftPad.length - boxWidth, 0))}`;
      lines[boxStart + 1] = `${leftPad}${paint("▌", "accent")}${paint(`  ${pad(promptBox[0], boxWidth - 3)}`, "subtle")}${" ".repeat(Math.max(cols - leftPad.length - boxWidth, 0))}`;
      lines[boxStart + 2] = `${leftPad}${paint("▌", "accent")}${paint(`  ${pad(promptBox[1], boxWidth - 3)}`, "text")}${" ".repeat(Math.max(cols - leftPad.length - boxWidth, 0))}`;
    }

    const tipRow = Math.min(height - 2, boxStart + 5);
    if (tipRow >= 0) lines[tipRow] = center(tip, cols, "warning");
    return lines;
  }

  private inputLine(cols: number): string {
    const prefix = `${this.prompt} `;
    const valueWidth = Math.max(cols - visibleLength(prefix) - 1, 1);
    return `${paint(prefix, "text")}${this.inputWithCursor(valueWidth)} `;
  }

  private accentLine(cols: number): string {
    return paint("─".repeat(cols), "accent");
  }

  private inputWithCursor(width: number): string {
    const chars = Array.from(this.input);
    const cursor = Math.max(0, Math.min(this.cursor, chars.length));
    let start = 0;
    let cursorWidth = 0;
    for (let i = 0; i < cursor; i += 1) cursorWidth += charWidth(chars[i] ?? "");
    while (cursorWidth - visibleLength(chars.slice(start, cursor).join("")) > width - 1) {
      start += 1;
    }

    const visibleChars = chars.slice(start);
    let used = 0;
    let rendered = "";
    for (let i = 0; i <= visibleChars.length; i += 1) {
      const absolute = start + i;
      const atCursor = absolute === cursor;
      const ch = visibleChars[i] ?? " ";
      const w = charWidth(ch);
      if (used + w > width) break;
      if (atCursor) {
        rendered += `\x1b[7m${ch}\x1b[0m`;
      } else if (i < visibleChars.length) {
        rendered += paint(ch, "text");
      }
      used += w;
      if (atCursor && absolute >= chars.length) break;
    }
    return rendered + " ".repeat(Math.max(width - used, 0));
  }

  private wrapVisibleLines(width: number): OutputLine[] {
    const result: OutputLine[] = [];
    for (const line of this.lines) {
      const chunks = wrapPlain(line.text, width);
      for (const chunk of chunks) result.push({ text: chunk, token: line.token });
    }
    return result;
  }

  private cursorMove(row: number, col: number): string {
    return `\x1b[${row};${col}H`;
  }
}

class TuiApp {
  private backend: NdjsonBackend;
  private screen = new Screen();
  private input = "";
  private cursor = 0;
  private busy = false;
  private history: string[] = [];
  private historyIndex = -1;
  private draft = "";
  private form: FormState | undefined;
  private inputBuffer = "";

  constructor() {
    this.history = loadHistory();
    this.backend = new NdjsonBackend((text) => {
      this.screen.add(text, "subtle");
      this.draw();
    });
  }

  async run(): Promise<void> {
    if (stdin.isTTY) stdin.setRawMode(true);
    stdout.write("\x1b[?1049h\x1b[?1000h\x1b[?1002h\x1b[?1006h\x1b[?1007l\x1b[?2004h\x1b[2J");
    this.draw();

    const onData = (chunk: Buffer | string) => {
      void this.handleInputData(chunk.toString());
    };
    stdin.on("data", onData);

    await new Promise<void>((resolve) => {
      const exit = () => resolve();
      process.once("SIGINT", exit);
      this.onceExit = exit;
    });

    stdin.off("data", onData);
    if (stdin.isTTY) stdin.setRawMode(false);
    stdin.pause();
    this.backend.close();
    stdout.write("\x1b[?2004l\x1b[?1006l\x1b[?1002l\x1b[?1000l\x1b[?1007h\x1b[?25h\x1b[?1049l");
  }

  private onceExit: (() => void) | undefined;

  private async handleInputData(chunk: string): Promise<void> {
    this.inputBuffer += chunk;
    while (this.inputBuffer.length > 0) {
      const consumed = await this.consumeInputBuffer();
      if (!consumed) break;
    }
  }

  private async consumeInputBuffer(): Promise<boolean> {
    if (this.inputBuffer.startsWith("\x1b[200~")) {
      const end = this.inputBuffer.indexOf("\x1b[201~");
      if (end < 0) return false;
      const pasted = this.inputBuffer.slice("\x1b[200~".length, end);
      this.inputBuffer = this.inputBuffer.slice(end + "\x1b[201~".length);
      this.insertText(pasted.replace(/\r?\n/g, " "));
      this.draw();
      return true;
    }

    const mouse = /^\x1b\[<(\d+);(\d+);(\d+)([mM])/.exec(this.inputBuffer);
    if (mouse) {
      this.inputBuffer = this.inputBuffer.slice(mouse[0].length);
      await this.handleMouse(Number(mouse[1]), Number(mouse[2]), Number(mouse[3]), mouse[4]);
      return true;
    }
    if (this.inputBuffer.startsWith("\x1b[<")) {
      if (!/[mM]/.test(this.inputBuffer) && this.inputBuffer.length < 24) return false;
      this.inputBuffer = this.inputBuffer.slice(1);
      return true;
    }

    const sequenceKey = this.readKnownSequence();
    if (sequenceKey) {
      this.inputBuffer = this.inputBuffer.slice(sequenceKey.sequence?.length ?? 0);
      await this.handleKey(sequenceKey);
      return true;
    }

    const csi = /^\x1b\[([0-9;]*)([A-Za-z~])/.exec(this.inputBuffer);
    if (csi) {
      this.inputBuffer = this.inputBuffer.slice(csi[0].length);
      if (csi[2] === "u" && (csi[1].startsWith("99;") || csi[1].startsWith("67;"))) {
        await this.copyCurrentSelection();
      }
      return true;
    }

    const first = Array.from(this.inputBuffer)[0] ?? "";
    if (!first) return false;
    this.inputBuffer = this.inputBuffer.slice(first.length);

    const code = first.codePointAt(0) ?? 0;
    if (first === "\x03") {
      await this.handleKey({ name: "c", ctrl: true, sequence: first });
    } else if (first === "\x11") {
      await this.handleKey({ name: "q", ctrl: true, sequence: first });
    } else if (first === "\x0c") {
      await this.handleKey({ name: "l", ctrl: true, sequence: first });
    } else if (first === "\r" || first === "\n") {
      await this.handleKey({ name: "return", sequence: first });
    } else if (first === "\x7f" || first === "\b") {
      await this.handleKey({ name: "backspace", sequence: first });
    } else if (first === "\x1b") {
      // Drop unknown escape sequences. In particular, never let mouse fragments
      // become editable text.
    } else if (code >= 0x20 && code !== 0x7f) {
      await this.handleKey({ sequence: first });
    }
    return true;
  }

  private readKnownSequence(): InputKey | undefined {
    const known: Array<[string, InputKey]> = [
      ["\x1b[A", { name: "up", sequence: "\x1b[A" }],
      ["\x1b[B", { name: "down", sequence: "\x1b[B" }],
      ["\x1b[C", { name: "right", sequence: "\x1b[C" }],
      ["\x1b[D", { name: "left", sequence: "\x1b[D" }],
      ["\x1b[H", { name: "home", sequence: "\x1b[H" }],
      ["\x1b[F", { name: "end", sequence: "\x1b[F" }],
      ["\x1b[1~", { name: "home", sequence: "\x1b[1~" }],
      ["\x1b[4~", { name: "end", sequence: "\x1b[4~" }],
      ["\x1b[3~", { name: "delete", sequence: "\x1b[3~" }],
      ["\x1b[5~", { name: "pageup", sequence: "\x1b[5~" }],
      ["\x1b[6~", { name: "pagedown", sequence: "\x1b[6~" }],
    ];
    for (const [sequence, key] of known) {
      if (this.inputBuffer.startsWith(sequence)) return key;
    }
    return undefined;
  }

  private async handleMouse(button: number, col: number, row: number, eventType: string): Promise<void> {
    if (button === 64) {
      this.screen.scrollBy(3);
      this.draw();
    } else if (button === 65) {
      this.screen.scrollBy(-3);
      this.draw();
    } else if (eventType === "m") {
      if (this.screen.endSelection(row, col)) {
        const text = this.screen.copyText();
        if (text) {
          await copyToClipboard(text);
          this.screen.clearSelection();
        }
        this.draw();
      }
    } else if ((button & 3) === 0) {
      const changed = (button & 32) === 32
        ? this.screen.updateSelection(row, col)
        : this.screen.beginSelection(row, col);
      if (changed) this.draw();
    } else if ((button & 3) === 3) {
      if (this.screen.clearSelection()) this.draw();
    }
  }

  private async handleKey(key: InputKey): Promise<void> {
    if (key.ctrl && key.name === "c") {
      await this.copyCurrentSelection();
      return;
    }
    if (key.ctrl && key.name === "q") {
      this.onceExit?.();
      return;
    }
    if (key.ctrl && key.name === "l") {
      this.screen.clear();
      this.draw();
      return;
    }
    if (key.name === "pageup") {
      this.screen.scrollBy(this.outputPageSize());
      this.draw();
      return;
    }
    if (key.name === "pagedown") {
      this.screen.scrollBy(-this.outputPageSize());
      this.draw();
      return;
    }
    if (this.busy) return;

    switch (key.name) {
      case "return":
        await this.submit();
        return;
      case "backspace":
        if (this.cursor > 0) {
          const chars = Array.from(this.input);
          chars.splice(this.cursor - 1, 1);
          this.input = chars.join("");
          this.cursor -= 1;
        }
        break;
      case "delete":
        {
          const chars = Array.from(this.input);
          chars.splice(this.cursor, 1);
          this.input = chars.join("");
        }
        break;
      case "left":
        this.cursor = Math.max(0, this.cursor - 1);
        break;
      case "right":
        this.cursor = Math.min(Array.from(this.input).length, this.cursor + 1);
        break;
      case "home":
        this.cursor = 0;
        break;
      case "end":
        this.cursor = Array.from(this.input).length;
        break;
      case "up":
        this.historyUp();
        break;
      case "down":
        this.historyDown();
        break;
      default:
        if (key.sequence && !key.ctrl && !key.meta && key.sequence >= " ") {
          this.insertText(key.sequence);
        }
        break;
    }
    this.draw();
  }

  private outputPageSize(): number {
    return Math.max((stdout.rows || 30) - 6, 1);
  }

  private insertText(text: string): void {
    if (!text) return;
    const chars = Array.from(this.input);
    const inserted = Array.from(text);
    chars.splice(this.cursor, 0, ...inserted);
    this.input = chars.join("");
    this.cursor += inserted.length;
    this.historyIndex = -1;
  }

  private async copyCurrentSelection(): Promise<void> {
    const text = this.screen.copyText();
    if (text) {
      await copyToClipboard(text);
      this.screen.clearSelection();
      this.draw();
    }
  }

  private async submit(): Promise<void> {
    const text = this.input.trim();
    this.input = "";
    this.cursor = 0;
    this.historyIndex = -1;
    if (!text && !this.form) {
      this.draw();
      return;
    }

    if (this.form) {
      await this.submitFormValue(text);
      return;
    }

    if (text === "/exit" || text === "exit" || text === "quit") {
      this.onceExit?.();
      return;
    }
    this.historyPush(text);
    this.screen.scrollToBottom();
    this.screen.addCommand(text);

    if (text === "/help" || text === "help") {
      this.screen.add("commands: /build /decode /connect /send /ports /close", "text");
      this.screen.add("local: /copy /exit", "subtle");
      this.screen.add("", "text");
      this.draw();
      return;
    }
    if (text === "/copy") {
      const ok = await copyToClipboard(this.screen.copyText());
      this.screen.add(ok ? "copied last result block" : "nothing copied", ok ? "success" : "warning");
      this.screen.add("", "text");
      this.draw();
      return;
    }

    await this.executeCommand(text);
  }

  private async executeCommand(text: string): Promise<void> {
    this.busy = true;
    this.screen.setStatus("BUSY");
    this.draw();
    try {
      const response = await this.backend.request({
        type: "command.execute",
        command: text.startsWith("/") ? text : `/${text}`,
        args: {},
      });
      this.handleResponse(response);
    } catch (error) {
      this.screen.add(error instanceof Error ? error.message : String(error), "error");
    } finally {
      this.busy = false;
      this.screen.setStatus("READY");
      this.draw();
    }
  }

  private async submitFormValue(value: string): Promise<void> {
    const form = this.form;
    if (!form) return;
    const field = form.fields[form.index];
    const key = field?.key ?? field?.name ?? "";
    if (key && value) form.args[key] = value;
    form.index += 1;
    if (form.index < form.fields.length) {
      this.setPromptForForm();
      this.draw();
      return;
    }

    this.busy = true;
    this.screen.setStatus("BUSY");
    this.screen.setPrompt(">");
    this.form = undefined;
    this.draw();
    try {
      const response = await this.backend.request({
        type: "interaction.continue",
        interaction_id: form.interactionId,
        args: form.args,
      });
      this.handleResponse(response);
    } catch (error) {
      this.screen.add(error instanceof Error ? error.message : String(error), "error");
    } finally {
      this.busy = false;
      this.screen.setStatus("READY");
      this.draw();
    }
  }

  private handleResponse(response: WireResponse): void {
    this.screen.renderResponse(response);
    if (response.status === "need_input" && response.interaction_id) {
      this.form = {
        interactionId: response.interaction_id,
        fields: response.input_schema ?? [],
        index: 0,
        args: {},
      };
      this.setPromptForForm();
    }
  }

  private setPromptForForm(): void {
    if (!this.form) {
      this.screen.setPrompt(">");
      return;
    }
    const field = this.form.fields[this.form.index];
    const key = field?.key ?? field?.name ?? "value";
    this.screen.setPrompt(`--${key}`);
  }

  private historyPush(text: string): void {
    const trimmed = text.trim();
    if (!trimmed) return;
    this.history = this.history.filter((item) => item !== trimmed);
    this.history.push(trimmed);
    this.history = this.history.slice(-HISTORY_LIMIT);
    saveHistory(this.history);
  }

  private historyUp(): void {
    if (!this.history.length) return;
    if (this.historyIndex === -1) {
      this.draft = this.input;
      this.historyIndex = this.history.length - 1;
    } else {
      this.historyIndex = Math.max(0, this.historyIndex - 1);
    }
    this.input = this.history[this.historyIndex] ?? "";
    this.cursor = Array.from(this.input).length;
  }

  private historyDown(): void {
    if (this.historyIndex === -1) return;
    if (this.historyIndex < this.history.length - 1) {
      this.historyIndex += 1;
      this.input = this.history[this.historyIndex] ?? "";
    } else {
      this.historyIndex = -1;
      this.input = this.draft;
    }
    this.cursor = Array.from(this.input).length;
  }

  private draw(): void {
    this.screen.setInput(this.input, this.cursor);
    this.screen.draw();
  }
}

async function runBatch(): Promise<void> {
  const backend = new NdjsonBackend((text) => stdout.write(paint(`${text}\n`, "subtle")));
  const rl = createInterface({ input: stdin, output: stdout, terminal: false });
  try {
    for await (const raw of rl) {
      const text = raw.trim();
      if (!text) continue;
      if (text === "/exit" || text === "exit" || text === "quit") break;
      const response = await backend.request({
        type: "command.execute",
        command: text.startsWith("/") ? text : `/${text}`,
        args: {},
      });
      writeBatchResponse(response);
    }
  } finally {
    rl.close();
    backend.close();
  }
}

function writeBatchResponse(response: WireResponse): void {
  if (response.status === "success") {
    const data = response.data ?? {};
    if (typeof data.path === "string") stdout.write(`${data.path}\n`);
    if (typeof data.frame === "string") stdout.write(`${data.frame}\n`);
    return;
  }
  stdout.write(`${response.status}: ${response.error ?? response.hint ?? ""}\n`);
}

async function copyToClipboard(text: string): Promise<boolean> {
  if (!text) return false;
  const command = process.platform === "darwin" ? "pbcopy" : process.platform === "win32" ? "clip" : "xclip";
  const args = process.platform === "linux" ? ["-selection", "clipboard"] : [];
  const child = spawn(command, args, { stdio: ["pipe", "ignore", "ignore"] });
  child.stdin.end(text);
  const [code] = (await once(child, "close")) as [number];
  return code === 0;
}

function pad(text: string, width: number): string {
  const value = fit(text, width);
  return value + " ".repeat(Math.max(width - visibleLength(value), 0));
}

function fit(text: string, width: number): string {
  if (visibleLength(text) <= width) return text;
  const suffix = "...";
  const target = Math.max(width - visibleLength(suffix), 0);
  let used = 0;
  let out = "";
  for (const ch of Array.from(text)) {
    const next = charWidth(ch);
    if (used + next > target) break;
    out += ch;
    used += next;
  }
  return out + suffix;
}

function fitSides(left: string, right: string, width: number): string {
  const gap = Math.max(width - visibleLength(left) - visibleLength(right), 1);
  return fit(left + " ".repeat(gap) + right, width);
}

function center(text: string, width: number, token: SemanticToken = "text"): string {
  const value = fit(text, width);
  const left = Math.max(Math.floor((width - visibleLength(value)) / 2), 0);
  const right = Math.max(width - left - visibleLength(value), 0);
  return `${" ".repeat(left)}${paint(value, token)}${" ".repeat(right)}`;
}

function visibleLength(text: string): number {
  return Array.from(text).reduce((sum, ch) => sum + charWidth(ch), 0);
}

function stripAnsi(text: string): string {
  return text.replace(/\x1b\[[0-?]*[ -/]*[@-~]/g, "");
}

function sliceCells(text: string, start: number, end: number): string {
  let col = 0;
  let out = "";
  for (const ch of Array.from(text)) {
    const width = charWidth(ch);
    const next = col + width;
    if (next > start && col < end) out += ch;
    if (next >= end) break;
    col = next;
  }
  return out;
}

function charWidth(ch: string): number {
  const code = ch.codePointAt(0) ?? 0;
  if (
    (code >= 0x1100 && code <= 0x115f) ||
    (code >= 0x2e80 && code <= 0xa4cf) ||
    (code >= 0xac00 && code <= 0xd7a3) ||
    (code >= 0xf900 && code <= 0xfaff) ||
    (code >= 0xfe10 && code <= 0xfe19) ||
    (code >= 0xfe30 && code <= 0xfe6f) ||
    (code >= 0xff00 && code <= 0xff60) ||
    (code >= 0xffe0 && code <= 0xffe6)
  ) {
    return 2;
  }
  return 1;
}

function wrapPlain(text: string, width: number): string[] {
  const chars = Array.from(text);
  if (!chars.length) return [""];
  const lines: string[] = [];
  let line = "";
  let used = 0;
  for (const ch of chars) {
    const next = charWidth(ch);
    if (used + next > width && line) {
      lines.push(line);
      line = "";
      used = 0;
    }
    line += ch;
    used += next;
  }
  if (line) lines.push(line);
  return lines;
}

function loadHistory(): string[] {
  try {
    if (!existsSync(HISTORY_FILE)) return [];
    return readFileSync(HISTORY_FILE, "utf8")
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean)
      .slice(-HISTORY_LIMIT);
  } catch {
    return [];
  }
}

function saveHistory(history: string[]): void {
  try {
    writeFileSync(HISTORY_FILE, `${history.slice(-HISTORY_LIMIT).join("\n")}\n`, "utf8");
  } catch {
    // History is a convenience feature; command execution must not depend on it.
  }
}

if (stdin.isTTY && stdout.isTTY) {
  new TuiApp().run().catch((error) => {
    if (stdin.isTTY) stdin.setRawMode(false);
    stdout.write(`\x1b[?1006l\x1b[?1000l\x1b[?25h\x1b[?1049l${paint("fatal", "error")}: ${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
  });
} else {
  runBatch().catch((error) => {
    stdout.write(`${paint("fatal", "error")}: ${error instanceof Error ? error.message : String(error)}\n`);
    process.exitCode = 1;
  });
}
