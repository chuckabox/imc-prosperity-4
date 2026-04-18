"""
Unified dashboard entrypoint (repo-level).

This keeps one stable launch path:
    streamlit run "tools/dashboard.py"

The implementation currently lives in:
    ROUND 1/tools/dashboard.py

That module is now round-agnostic and can switch round folders from the UI.
"""

import importlib.util
import os
import traceback
import streamlit as st


def _load_dashboard_module():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    impl_path = os.path.join(repo_root, "ROUND 1", "tools", "dashboard.py")
    if not os.path.exists(impl_path):
        raise FileNotFoundError(
            f"Unified dashboard implementation not found at: {impl_path}"
        )

    spec = importlib.util.spec_from_file_location("p4_unified_dashboard_impl", impl_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to build import spec for: {impl_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    try:
        module = _load_dashboard_module()
        if not hasattr(module, "main"):
            raise AttributeError("Dashboard module does not export `main()`.")
        module.main()
    except Exception as exc:
        st.set_page_config(page_title="Dashboard Bootstrap Error", layout="wide")
        st.error("Failed to start unified dashboard.")
        st.exception(exc)
        with st.expander("Traceback", expanded=False):
            st.code(traceback.format_exc())


if __name__ == "__main__":
    main()
