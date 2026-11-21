"""AgroNova — Smart Farming Assistant (Generative AI · Groq / xAI Grok · Streamlit).

Run locally:   streamlit run app.py
Deploy:        push to GitHub → share.streamlit.io → New app → app.py, add GROQ_API_KEY (or an xAI key) in Secrets.
"""
import streamlit as st

st.set_page_config(page_title="AgroNova · Smart Farming AI", page_icon=":material/eco:", layout="wide",
                   initial_sidebar_state="collapsed")

from agronova import llm, prompts, state, theme, views  # noqa: E402

state.init()
theme.inject()

PAGES = {
    "home": st.Page(views.page_home, title="Home", icon=":material/home:", url_path="home", default=True),
    "map": st.Page(views.page_map, title="Farm Locator", icon=":material/map:", url_path="locator"),
    "chat": st.Page(views.page_chat, title="AgroNova AI", icon=":material/forum:", url_path="assistant"),
    "studio": st.Page(views.page_studio, title="Feature Studio", icon=":material/eco:", url_path="studio"),
    "validate": st.Page(views.page_validation, title="Validation Lab", icon=":material/science:", url_path="validation"),
    "monitor": st.Page(views.page_monitor, title="Usage", icon=":material/monitoring:", url_path="usage"),
    "story": st.Page(views.page_storyboard, title="Storyboard", icon=":material/menu_book:", url_path="storyboard"),
}
views.PAGES.update(PAGES)


@st.cache_data(ttl=3600, show_spinner=False)
def available_models(key: str) -> list[str]:
    try:
        return llm.list_models(llm.make_client(key))
    except Exception:
        return []


with st.sidebar:
    st.markdown("## Agro*Nova*")
    st.caption("Field intelligence · built-in AI")
    key = state.api_key()          # the app's own key, from server secrets: visitors never handle keys
    models = available_models(key) if key else []
    chat_models = [m for m in models if m in llm.MODEL_LABELS] + [m for m in models if m not in llm.MODEL_LABELS and "allam" not in m]
    st.selectbox("AI model", chat_models or list(llm.MODEL_LABELS), key="model",
                 format_func=lambda m: llm.MODEL_LABELS.get(m, m))
    st.selectbox("Answer language", prompts.LANGUAGES, key="language")
    with st.expander("AI abilities", expanded=False):
        st.toggle("Web search & calculations", True, key="use_web",
                  help="Searches the web for prices, schemes and news, and runs exact calculations in a sandbox.")
        st.toggle("Live farm data", True, key="use_tools", help="Weather, soil, crop calendar and place lookup.")
        st.toggle("Show reasoning", True, key="thinking", help="Shows how the model thought it through, in a collapsible panel.")
        st.toggle("Safety screening", True, key="use_guard", help="Llama Prompt Guard blocks jailbreak and prompt-injection attempts.")
    with st.expander("Generation parameters", expanded=False):
        st.slider("Temperature", 0.0, 1.5, 0.6, 0.05, key="temperature",
                  help="Lower = focused & consistent; higher = more creative / varied.")
        st.slider("Max output tokens", 256, 8192, 2048, 128, key="max_tokens",
                  help="Upper limit on answer length (≈ 0.75 words per token).")
    lab = state.place_label()
    st.caption(f"FARM — {lab or 'not pinned'}")
    st.caption("AI — " + ("online · voice, vision, web search" if models else "offline"))

nav = st.navigation(list(PAGES.values()), position="top")
nav.run()
