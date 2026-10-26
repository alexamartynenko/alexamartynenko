"""Claude calls: post drafts, rewrites, reply drafts, daily content ideas."""

import os

import anthropic

MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("CLAUDE_EFFORT", "low")

client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY

BRAND = """You ghostwrite X (Twitter) posts for @jexor_studio, the account of Alexandra Marty.

Who she is:
- Affiliate & performance marketing expert, 14 years in the industry, ex CMO of Notcoin and Bitfinex.
- Closed her agency (peak team: 70 people) to build her own products.
- Now teaches traffic and marketing for ANY business: affiliate, game mechanics, partner marketing
  that grows a business without big investment. All of it FOR FREE, no paywall.
- Story arc: poor family -> crypto in 2016 -> agency -> own products.

Topics: finding traffic for any product; monetizing any product; affiliate marketing in practice;
partner marketing in 2026; traffic channels that work; why most companies break when scaling;
mistakes that cost money; her personal story.

Every post MUST have:
1. A strong hook in the first line (provocative, curiosity, a number, a confession).
2. An open loop / curiosity gap that makes people read to the end or wait for the next post.
3. A CTA or question at the end (reply, vote, follow, bookmark, turn on notifications).

Tone: English, native and punchy, never a literal translation. Alive and emotional, written for
empaths: storytelling, feelings, vulnerability, talk directly to the reader ("have you ever..."),
short lines with breathing room. First person, she is a woman. Humor and memes are fine.
NOT dry, NOT brief-like, NOT corporate. No hashtags unless asked. No emojis spam (0-2 max).

Facts: never invent concrete numbers, user counts, client names or life events she has not given.
If a fact is needed, put a placeholder like [NUMBER] or [CLIENT] so she fills it in.
Keep a single post under 280 characters unless asked for a thread or a long post."""


def _ask(system: str, user: str, *, tools=None, max_tokens=8000) -> str:
    kwargs = dict(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"effort": EFFORT},
    )
    if tools:
        kwargs["tools"] = tools
    if MODEL in ("claude-opus-5-5", "claude-sonnet-5-5", "claude-opus-5", "claude-fable-5-1"):
        # If a safety classifier declines, retry server-side on a fallback model.
        kwargs["betas"] = ["server-side-fallback-2026-07-01"]
        kwargs["fallbacks"] = "default"

    messages = kwargs["messages"]
    for _ in range(5):  # resume server-tool turns that pause
        response = client.beta.messages.create(**kwargs)
        if response.stop_reason != "pause_turn":
            break
        messages = messages + [{"role": "assistant", "content": response.content}]
        kwargs["messages"] = messages

    if response.stop_reason == "refusal":
        return "Claude declined this request. Try rephrasing it."
    return "".join(b.text for b in response.content if b.type == "text").strip()


def draft_post(idea: str) -> str:
    return _ask(
        BRAND,
        "Write ONE X post from this idea or voice-note transcript. It may be in Russian; "
        "the post must be in English. Output only the post text, nothing else.\n\n"
        f"Idea:\n{idea}",
    )


def rewrite_post(post: str, feedback: str) -> str:
    return _ask(
        BRAND,
        "Rewrite this X post following Alexandra's feedback (it may be in Russian). "
        "Output only the new post text.\n\n"
        f"Post:\n{post}\n\nFeedback:\n{feedback}",
    )


def draft_replies(tweet: str) -> str:
    return _ask(
        BRAND,
        "Alexandra wants to reply under someone else's post to get noticed by founders and "
        "marketers. Write 3 different reply options, 1-3 sentences each, in English, first "
        "person. Each must add a real thought, angle or experience-based insight, never "
        "'Great post!'. No links, no self-promotion. Use placeholders instead of invented facts.\n"
        "Format exactly:\n1) ...\n\n2) ...\n\n3) ...\n\n"
        f"The post (text or link, may be incomplete):\n{tweet}",
        max_tokens=4000,
    )


def daily_ideas(topics: str) -> str:
    return _ask(
        BRAND,
        "Search the web for what is being discussed in the last 1-3 days around these topics: "
        f"{topics}.\n"
        "Pick the 3 most promising news items, debates or trends that Alexandra could react to "
        "with her own experience. For each one write:\n"
        "IDEA N: one line in Russian, what it is and why it fits her\n"
        "SOURCE: the link\n"
        "POST: a ready X post in English that follows all the rules\n\n"
        "Separate ideas with a line containing only ---",
        tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 5}],
        max_tokens=16000,
    )
