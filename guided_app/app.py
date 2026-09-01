"""Guided chat UI: instead of one free-text question, the app asks
for company, then period, then variables, one at a time, each as its
own short, direct reply. Once all three are collected, it runs the
real fetch/match pipeline and shows the answer.

The chat reply itself stays clean, just the variable name and its
value, no raw XBRL tag names. The real matched tag for each variable
is shown separately in the details panel instead.
"""
import gradio as gr

from resolver import PER_SHARE_VARS, display_name, resolve_from_fields
from extraction import advance, new_state

FIRST_QUESTION = "Which company would you like to ask about? (Example: Apple)"
NO_DETAILS = "Ask a question to see what got extracted."

THINKING = '<div class="typing-indicator"><span></span><span></span><span></span></div>'
TYPING_CSS = """
.typing-indicator { display:inline-flex; align-items:center; gap:4px; padding:4px 0; }
.typing-indicator span {
    width:7px; height:7px; border-radius:50%; background:currentColor; opacity:0.4;
    animation: typing-bounce 1.2s infinite ease-in-out;
}
.typing-indicator span:nth-child(2) { animation-delay: 0.2s; }
.typing-indicator span:nth-child(3) { animation-delay: 0.4s; }
@keyframes typing-bounce {
    0%, 60%, 100% { transform: translateY(0); opacity: 0.4; }
    30% { transform: translateY(-5px); opacity: 1; }
}
"""


def clean_summary(result):
    """The chat reply: just variable name and value, no raw tag."""
    if not result["ok"]:
        return result["error"]

    lines = []
    for r in result["results"]:
        name = display_name(r["variable"])
        if "error" in r:
            lines.append(f"{name}: {r['error']}")
        elif r["value"] is None:
            lines.append(f"{name}: no value resolved")
        else:
            unit = "" if r["variable"] in PER_SHARE_VARS else "M"
            lines.append(f"{name}: {r['value']:,.2f}{unit}")

    header = f"{result['ticker']} for {result['quarter']} {result['year']}:"
    return header + "\n" + "\n".join(f"  {line}" for line in lines)


def details_panel(result, company_name):
    """The side panel: company, ticker, period, and the real matched
    tag behind each variable's value."""
    if not result["ok"]:
        return f"**Error**\n\n{result['error']}"

    lines = [
        f"**Company:** {company_name}",
        f"**Ticker:** {result['ticker']}",
        f"**Period:** {result['quarter']} {result['year']} ({result['period_end']})",
        "",
    ]
    for r in result["results"]:
        name = display_name(r["variable"])
        if "error" in r:
            lines.append(f"**{name}:** {r['error']}")
        elif isinstance(r["selected"], list):
            matched = ", ".join(r["selected"])
            lines.append(f"**{name}** matched: `{matched}`")
        else:
            # no direct tag for this one, computed instead (e.g. Gross
            # Profit as Revenue - Cost of Revenue) - not a real match,
            # so it shouldn't be phrased as one
            lines.append(f"**{name}:** no direct tag, computed as {r['selected']}")
    return "\n\n".join(lines)


def start():
    """Clears the chat and asks the first question again - used both
    for the very first click (labeled Start) and every click after
    (relabeled Restart), so restarting always begins from a clean
    conversation, not appended onto the old one. Also enables the
    textbox, which starts out disabled so the user can't type an
    answer before there's a question to answer."""
    history = [{"role": "assistant", "content": FIRST_QUESTION}]
    return history, new_state(), gr.update(value="Restart"), NO_DETAILS, gr.update(interactive=True)


def respond(message, history, state):
    """A generator, not a plain function - yields once immediately to
    show the user's message right away, then again once the model has
    actually finished, instead of both appearing together only after
    the model call (which takes several real seconds) completes."""
    if state is None or state.get("step") is None:
        state = new_state()

    if not message.strip():
        yield history + [{"role": "assistant", "content": "Type an answer first."}], state, gr.update(), ""
        return

    # show the user's message and an animated thinking placeholder
    # immediately, and clear the textbox right away too, before the
    # model starts working
    history = history + [{"role": "user", "content": message}, {"role": "assistant", "content": THINKING}]
    yield history, state, gr.update(), ""

    state, next_prompt = advance(state, message)

    if next_prompt is not None:
        history = history[:-1] + [{"role": "assistant", "content": next_prompt}]
        yield history, state, NO_DETAILS, gr.update()
        return

    result = resolve_from_fields(state["ticker"], state["entry"], state["variables"], state["year"], state["quarter"])
    answer = clean_summary(result)
    answer += "\n\nClick Restart to start fresh, or just type the name of the next company."
    history = history[:-1] + [{"role": "assistant", "content": answer}]
    yield history, new_state(), details_panel(result, state["entry"]["name"]), gr.update()


with gr.Blocks(title="Financial Question Extraction (guided)") as demo:
    gr.Markdown("## 💬 Financial Question Extraction (guided)")
    with gr.Row():
        with gr.Column(scale=2):
            chatbot = gr.Chatbot(label=None, height=450)
            start_btn = gr.Button("Start")
            textbox = gr.Textbox(placeholder="Type your answer here", show_label=False, interactive=False)
        with gr.Column(scale=1):
            gr.Markdown("### Extraction details")
            details = gr.Markdown(NO_DETAILS)
    state = gr.State(new_state())

    start_btn.click(start, None, [chatbot, state, start_btn, details, textbox])
    textbox.submit(respond, [textbox, chatbot, state], [chatbot, state, details, textbox], show_progress="hidden")

if __name__ == "__main__":
    # server_name="0.0.0.0" so this is reachable from outside a Docker
    # container - Gradio's default (127.0.0.1) only accepts connections
    # from inside the container itself, so port mapping alone wouldn't
    # be enough without this.
    demo.launch(theme=gr.themes.Soft(), css=TYPING_CSS, server_name="0.0.0.0")
