# conv-tree

A herdr plugin that shows your Claude Code conversations as a tree of the prompts you sent, in a pane next to your work.

- Branches created by rewind and branches that live in separate files after a fork are joined into a single tree.
- The current position of the focused Claude pane is marked with `▶`. Positions of other Claude panes are marked with `▷`.
- You can fork from any past prompt, or send the gist of one branch to another (merge). New conversations open in a new pane beside the current one; the original pane is left untouched.

## Setup

```bash
cd /path/to/conv-tree
uv sync
herdr plugin link .
```

To open the tree with a key, add the following to `~/.config/herdr/config.toml` (pick any key you like):

```toml
[[keys.command]]
key = "prefix+alt+t"
type = "plugin_action"
command = "conv-tree.open"
description = "conversation tree"
```

Then run `herdr server reload-config`. Press the key in a Claude Code pane and the tree opens to the right of that pane.

## Keys (tree pane)

| Key | Action |
|---|---|
| ↑ / ↓, Enter | Move, expand / collapse a branch |
| `o` | Open the conversation as of the selected prompt (including its result) in a new pane. Nothing is sent. If a pane is already at that position, focus that pane instead. If a session ends there, resume that session as is; if the prompt is in the middle of a conversation, create a new fork and open it |
| `f` | Fork from **just before** the selected prompt. Claude opens in a new pane with that prompt typed into the input box (not sent), so you can edit and resend it |
| `b` | Mark the selected prompt as the merge source (`◆`). Press again to unmark |
| `m` | Send the gist (prompts and results) of the branch marked with `b` to the conversation as of the selected prompt. An editor opens before sending (`ctrl+s` send, `ctrl+o` switch target, `esc` cancel). **By default, if an idle pane is sitting at the selected prompt, the text is sent directly to that pane (no new fork).** `ctrl+o` switches to "create a new fork and open it in a new pane". If no such pane exists or it is busy, only the new-fork option is available |
| `c` | Jump to the current position |
| `s` | Toggle the **branches-only** view. Only the first prompt, branch points, the first prompt of each branch, the last prompt of each branch and prompts marked `▶` `▷` `◆` are shown; linear runs in between collapse into `… N more` |
| `q` | Quit |

## Notes

- Existing conversation files are never modified. Each fork, and each merge that creates a new fork, writes one new session file to `~/.claude/projects/<project>/`. A merge sent directly to a pane creates no file; it just adds a message to that conversation.
- Only the conversation branches. Files (code) on disk are not branched.
- `▶` marks the *last recorded* position. Right after a rewind in Claude Code, it keeps pointing at the old position until you send the next prompt.
- If the Claude in a new pane shows a confirmation such as "Do you trust this folder?", conv-tree types nothing and waits up to 2 minutes for you to answer. After you answer, the prompt or merge text is sent.
- When you run `herdr plugin action invoke open` from the CLI, herdr uses **the pane focused in the UI** as the anchor.

## Development

```bash
uv run pytest -q
uv run conv-tree --cwd /path/to/project                   # view only, outside herdr
uv run conv-tree --cwd /path/to/project --branches-only   # start in the branches-only view
```
