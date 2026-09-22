"""UI variant 1: classic ChatGPT-style chat log, bubble messages,
input box fixed below the chat, example questions as buttons below
the input box (not mixed into the chat transcript, not above it)."""
import sys
from pathlib import Path

import gradio as gr

sys.path.insert(0, str(Path(__file__).parent))
from qa_backend import stream_answer

CSS = """
.gradio-container { max-width: 1100px !important; margin: 0 auto !important; padding-top: 0.25rem !important; }
#title { text-align: center; margin-bottom: 0; font-size: 1.6rem !important; }
#subtitle { text-align: center; color: var(--body-text-color-subdued); margin-top: 0; margin-bottom: 0.35rem; font-size: 0.85rem !important; }
#chatbot .message,
#chatbot .message-content,
#chatbot .message-text,
#chatbot .message-wrap,
#chatbot .prose,
#chatbot p { font-size: 0.8rem !important; line-height: 1.4 !important; }
#question-box textarea { font-size: 0.8rem !important; }
#examples-row { margin-top: 0.75rem !important; }
"""

EXAMPLES = [
    "What was Apple's revenue in Q1 2025?",
    "What was Microsoft's net income and operating income in Q2 2024?",
    "What was Tesla's total assets in 2023?",
]


def flow(message, history):
    """Locks the textbox, send button, and example buttons while a
    question is being answered, so a second question can't be
    submitted mid-pipeline - two questions loading models onto the
    same GPU at once is what crashed an earlier version of this app."""
    n_locks = 2 + len(EXAMPLES)  # textbox, send, and each example button

    if not message or not message.strip():
        yield ("",) + (history,) + (gr.update(interactive=True),) * (n_locks - 1)
        return

    history = history + [{"role": "user", "content": message}, {"role": "assistant", "content": ""}]
    locked_textbox = gr.update(value="", interactive=False)
    locked = gr.update(interactive=False)
    yield (locked_textbox, history) + (locked,) * (n_locks - 1)

    for chunk in stream_answer(message):
        history[-1]["content"] = chunk
        yield (gr.update(), history) + (locked,) * (n_locks - 1)

    unlocked = gr.update(interactive=True)
    yield (gr.update(interactive=True), history) + (unlocked,) * (n_locks - 1)


with gr.Blocks(theme=gr.themes.Soft(primary_hue="indigo", neutral_hue="slate"), css=CSS, title="SEC Filing Assistant") as demo:
    gr.Markdown("# SEC Filing Assistant", elem_id="title")
    gr.Markdown("Ask about a public company's real reported financials, covering data from 2020 onward.", elem_id="subtitle")

    chatbot = gr.Chatbot(layout="bubble", show_label=False, elem_id="chatbot", height=460, buttons=[])

    with gr.Row():
        textbox = gr.Textbox(placeholder="Ask a question...", show_label=False, scale=8, container=False, elem_id="question-box")
        send = gr.Button("Send", scale=1, variant="primary")

    with gr.Row(elem_id="examples-row"):
        example_buttons = [gr.Button(ex, size="sm", variant="secondary") for ex in EXAMPLES]

    lock_targets = [send] + example_buttons

    textbox.submit(flow, [textbox, chatbot], [textbox, chatbot] + lock_targets)
    send.click(flow, [textbox, chatbot], [textbox, chatbot] + lock_targets)
    for btn in example_buttons:
        btn.click(lambda ex=btn.value: ex, None, textbox).then(flow, [textbox, chatbot], [textbox, chatbot] + lock_targets)

if __name__ == "__main__":
    demo.queue().launch(server_port=7860, footer_links=["settings"])
