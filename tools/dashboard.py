"""
Unified dashboard entrypoint (repo-level).

This keeps one stable launch path:
    streamlit run "tools/dashboard.py"

The implementation lives in:
    tools/impl/unified_dashboard.py

That module is round-agnostic and can switch round folders from the UI.
"""

import importlib.util
import os
import traceback
import streamlit as st


def _load_dashboard_module():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    impl_path = os.path.join(repo_root, "tools", "impl", "unified_dashboard.py")
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
    except ModuleNotFoundError as exc:
        st.set_page_config(page_title="Dashboard Bootstrap Error", layout="wide")
        st.error("Failed to start unified dashboard (missing dependency).")
        st.exception(exc)
        st.info(
            "Install dashboard dependencies from the repo root:  "
            "`pip install -r requirements-dashboard.txt`"
        )
    except Exception as exc:
        st.set_page_config(page_title="Dashboard Bootstrap Error", layout="wide")
        st.error("Failed to start unified dashboard.")
        st.exception(exc)
        with st.expander("Traceback", expanded=False):
            st.code(traceback.format_exc())


if __name__ == "__main__":
    main()
