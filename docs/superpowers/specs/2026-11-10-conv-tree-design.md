# conv-tree: herdr 上の Claude Code 会話ツリー — 設計書

日付: 2026-11-10

## 1. 目的と背景

利用者は AI の研究者で、herdr（ターミナル上でコーディングエージェントを管理するワークスペースマネージャ、v0.8.0）の中で Claude Code を使っている。研究では同じ会話から何度も fork や rewind をして別の案を試す。そうするうちに次の2つがわからなくなる。

1. **どの枝が何を試したものか**
2. **自分が今、会話全体のどこにいるか**

conv-tree は、1つのプロジェクトフォルダにある Claude Code の会話を木として herdr のペインに常に表示する。今いる位置に印を付け、木の上から「ここから分岐」「merge」を簡単に行えるようにする。

## 2. ゴール

- G1. プロジェクトフォルダの Claude Code 会話を、rewind による枝分かれと fork によるファイルをまたいだ枝の両方を含めて、1つの木（無関係な会話は別の木）として表示する。
- G2. 各枝は**分岐点で利用者が送った指示（user プロンプト）**で見分けられるようにする。これが見分けの主な手がかりになる（利用者の回答）。
- G3. 「今ここ」の印は、herdr で**フォーカスされている Claude Code ペイン**の現在位置に付いていく（利用者の回答）。
- G4. 木の中のノード（指示）を選んで「ここから続ける」と、その時点までの会話を新しいセッションとして作り、**新しいペインで横に開く**。元のペインには手を付けない（利用者の回答）。
- G5. **merge**: 2つの枝 A と B を選ぶと、B の要点（指示と結果）をまとめ、A を新しいペインで開いて最初のメッセージとして送る。目的は、別の枝で試したアイデアの結果を1つの会話に集めて比較すること（利用者の回答: 「要点をまとめてどちらかに送る形でいい」）。
- G6. 木は**作業中ずっと横に表示しておく**常駐ペイン（利用者の回答）。会話が進んだり枝が増えたりしたら自動で更新する。

### 使われ方（利用者の回答）
- コードは**メインの枝からサブエージェントに書かせる**。fork した枝は、実験計画を練る、サーベイをする、短い会話をする、といった**会話が中心の用途**で使う。
- そのため fork で分岐するのは**会話だけ**とし、ファイルは分岐させない（git worktree やファイル履歴の巻き戻しは行わない）。fork 先のペインは元と同じ cwd で開く。

## 3. 非ゴール

- fork や merge のときにファイルを分岐させたり、巻き戻したりすること（worktree の作成、`file-history-snapshot` の再生など）。

- 2つの会話履歴を1本に完全に合わせる、git のような本当のマージ（会話が一本道の列なので意味が通らない）。
- 動いている Claude Code プロセスを外から rewind させること（外部 API がない）。
- Claude Code 以外のエージェント（codex など）への対応。
- 複数プロジェクトをまたいだ表示。対象はツリーペインの cwd に対応するプロジェクトだけ。
- 会話ファイルの削除や書き換え。既存の jsonl は**読むだけ**にする（新しく作るのは fork 用のファイルだけ）。

## 4. 失敗とみなすこと

利用者は「わからない、使ってみてから」と答えている。以下は私の判断で設定したもの。

- 既存の会話ファイルを壊す、または変更する。
- 木が大きいセッション（約3万行、数十 MB の jsonl を確認済み）で固まる、または更新が数秒以上遅れる。
- 「今ここ」が間違ったノードを指す（存在しない位置を示すより悪い）。

## 5. 調査で確認した事実

Claude Code 2.1.322 と herdr 0.8.0 で確認した。

### Claude Code の履歴

- 保存場所は `~/.claude/projects/<cwd の / を - に置換>/<sessionId>.jsonl`。1行に1レコード。
- 会話レコード（`type` が `user` / `assistant` / `system` / `attachment` など）は `uuid` と `parentUuid` を持ち、木構造になる。他に `isSidechain`、`timestamp`、`sessionId`、`message`、`isMeta`、`isCompactSummary`、`promptId` などのフィールドがある。
- `uuid` を持たないメタレコードもある（`last-prompt`、`ai-title`（`aiTitle`）、`mode`、`permission-mode`、`file-history-snapshot`、`queue-operation`、`leafUuid` を持つものなど）。
- **rewind** は同じファイル内での分岐として現れる。同じ `parentUuid` を持つ子が複数できる（ある大きなセッションで10か所を確認）。
- **fork**（`claude --resume <id> --fork-session`、または UI の fork）は新しいファイルを作り、元のメッセージの `uuid` をそのまま引き継ぐ（2ファイル間で492件の uuid が共通していることを確認）。つまり uuid の和集合で、ファイルをまたいだ1本の木を組み立てられる。
- コンパクト（`isCompactSummary`、`compactMetadata`）も存在する。
- 起動中の Claude Code ごとに `~/.claude/sessions/<pid>.json` があり、`pid`、`sessionId`、`cwd`、`status`、`name` などを持つ。
- CLI には `--resume <id>`、`--fork-session`、`--session-id <uuid>` がある。

### herdr

- プラグイン機能がある。マニフェストは `herdr-plugin.toml`（リポジトリ直下に空のファイルを用意済み）。CLI は `herdr plugin link <path>`、`plugin list`、`plugin pane open --plugin ID --entrypoint ID [--placement overlay|popup|split|tab|zoomed] [--direction right|down] ...`、`plugin action list|invoke`、`plugin log list`。
- マニフェストのセクションはバイナリから読み取った名前で、`name`、`version`、`min_herdr_version`、`platforms`、`build`、`startup`、`panes`（`title`、`placement`、`width`、`height` など）、`actions`、`events`（`on`）、`link_handlers` がある。**公式ドキュメントは未確認**なので、正確な書き方は実装時に確かめること。
- プラグインのプロセスには `HERDR_PLUGIN_ROOT`、`HERDR_PLUGIN_STATE_DIR`、`HERDR_PLUGIN_CONFIG_DIR`、`HERDR_PLUGIN_CONTEXT_JSON`、`HERDR_PLUGIN_EVENT_JSON`、`HERDR_SOCKET_PATH`、`HERDR_BIN_PATH` などの環境変数が渡される。
- `herdr agent list` / `agent get` で、各ペインの Claude Code（`pane_id`、`cwd`、`focused`、`agent_status`）が取れる。
- `herdr pane process-info --pane <id>` でペインの前面プロセスの pid が取れる。**pane → pid → `~/.claude/sessions/<pid>.json` → sessionId** の順でたどれる（確認済み）。
- イベントがある（`pane.focused`、`pane.agent_status_changed`、`pane.created`、`pane.closed` など）。購読するか、マニフェストの `events` フックで受け取れる。
- `herdr pane split --current --direction right --cwd ... --no-focus`、`herdr agent start <name> --kind claude --pane <id> -- <args>`、`herdr agent prompt <target> <text>` で、新しいペインに Claude を起動してプロンプトを送れる。
- herdr には Claude 用の公式連携（`herdr integration install claude`、フック経由で `agent_session_path` を報告する仕組みらしい）があるが、**この環境では未インストール**。

## 6. 決まっていること

### 6.1 形
- herdr プラグインとして作る。リポジトリ直下の `herdr-plugin.toml` がマニフェスト。開発中は `herdr plugin link .` で使う。
- ツリーは常駐ペインとして横（split, right）に開く。キーまたはアクションで開閉できるようにする。
- **言語は Python、TUI は Textual**（私の判断。利用者は反対していない。研究で Python を使う利用者が手を入れやすいため）。依存は uv で管理する（uv は `/usr/local/bin/uv` にある。Textual は未インストール）。

### 6.2 木の作り方
- 対象プロジェクトのディレクトリ内のすべての `*.jsonl` を読み、`uuid` で重複を除いて1つのグラフにまとめる。
- 表示するノードは**利用者が送った指示**（user レコードのうち、本物のプロンプトであるもの）だけ。ツール結果、`isMeta`、コマンド出力、サイドチェーンは表示しない。assistant の応答やツール呼び出しは、指示ノードの間にまとめて隠す。
- 枝分かれは「同じ親（指示ノード単位でまとめた親）から複数の子指示がある」ことで判定する。
- 根が別の会話（共通の uuid がない）は別の木とし、新しい順に並べる（私の判断）。
- 各ノードには、指示の先頭部分（1行に切り詰める）、時刻、その指示を含むセッション（複数ありうる）を表示する。
- 選んだノードについて、指示の全文と、その指示に対する最後の assistant の結果を詳細欄に表示する。

### 6.3 「今ここ」
- herdr でフォーカスされている Claude Code ペインを取り（同じ cwd のものに限る）、pane → pid → `sessions/<pid>.json` → sessionId とたどる。
- そのセッションの jsonl で、**最後に追記された会話レコード**を現在の葉とし、それを含む指示ノードに印を付ける。
- 同じタブに Claude ペインが複数あるときは、最後にフォーカスされたものに付いていく（利用者の回答）。木には、他に開いているペインの位置も別の弱い印で示す（私の判断）。
- **rewind 直後のずれ**（私の判断）: 実行中のセッションで rewind しても、次の指示を送るまで jsonl には何も書かれないことがある。その間、印は rewind 前の位置を指したままになる。これは受け入れる。ただし、印には「最後に記録された位置」であることがわかる表示を添える。herdr の公式 Claude 連携など、フックで正確な位置が取れる手段が見つかれば、それを優先して使ってよい。

### 6.4 「ここから続ける」（fork）
- ノードを選び、キーで実行する。
- 新しい sessionId を作り、根から選んだノードまでの経路にあるレコード（＋必要なメタレコード）を新しい jsonl として同じプロジェクトディレクトリに書く。選んだ指示そのものは含めるか、その直前で切って指示を入力欄に入れておくかは 7 章で扱う。
- `herdr pane split --direction right --no-focus`（元のペインの右）で新しいペインを作り、`herdr agent start <name> --kind claude --pane <新ペイン> -- --resume <新sessionId>` で起動する。
- 既存のファイルには触れない。

### 6.5 merge
- 枝 A と B の2つのノードを選ぶ（A が送り先、B が持ち込む側）。以下は私の判断。
- **B の範囲**: A と B の共通の祖先より後から、選んだノード B まで（B を含む）の経路。B より下の枝は含めない。B の指示に対する結果も含める。共通の祖先がない（別の木の）場合は、B の根から B までの全体を使う。
- **A の開き方**: A の指示**と、それに対する結果を含めた**状態（A の直後）で開く。6.4 の fork は指示の直前で切るが、merge では切らない。fork ファイルを作る処理は共通にし、「ノードの直前で切る／直後で切る」を引数で選べるようにする。
- B から、各指示と、それぞれに対する最後の結果を抜き出して要約テキストを作る。
- A を新しいペインに開き、`herdr agent prompt` で要約を最初のメッセージとして送る。
- 要約は、まず機械的な抜き出し（指示＋最後の結果の短縮版）で作る。送る前にテキストを確認・編集できる画面を挟む（私の判断）。Claude に要約させる方法は、設定で選べる追加機能とする。

### 6.6 更新
- jsonl ファイルを監視し（ファイルサイズの変化を見て差分だけ読む）、herdr のフォーカスイベントで「今ここ」を更新する。ポーリングの場合は 1 秒程度の間隔とする。

## 7. 実装者に任せること

- マニフェストの正確な書き方（実際の herdr 0.8.0 で試して決める）。
- 本物のプロンプトとそれ以外の user レコードの見分け方（`toolUseResult`、`isMeta`、`<command-name>` などのタグ、`promptId` などの手がかりを調べて決める）。
- fork ファイルの作り方の詳細。最小限必要なレコードとフィールド、`sessionId` の書き換え、コンパクトをまたぐ経路の扱い。Claude Code で実際に `--resume` が通ること、そして `--fork-session` でできるファイルと同じ形になっていることを確かめる。代わりに、`claude --resume <元id> --fork-session` を使ったあとで rewind 位置を指定する方法があるならそちらでもよい。選んだ指示を含めるか、直前で切るかもここで決める（推奨は、選んだ指示の**直前**で切り、指示を編集して送り直せるようにすること）。
- キー割り当て、色、レイアウトの細部。
- 大きなファイルへの性能対策（キャッシュや差分読み込み）。
- 公式の herdr Claude 連携を使うか、6.3 の pid 方式を使うか。

## 8. 制約

- 既存の会話ファイルを書き換えない。
- 動作環境は Linux、Python 3.12、herdr 0.8.0、Claude Code 2.1.322。
- 利用者のプロジェクトの jsonl は大きくなりうる（数万行）。
