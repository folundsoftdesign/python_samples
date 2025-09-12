# ruff: noqa

import streamlit as st
from streamlit_cookies_controller import CookieController

st.set_page_config("Cookie QuickStart", "🍪", layout="wide")

controller = CookieController()

# Set a cookie
cookie = st.text_input("Set cookie", "")
controller.set(cookie, "xyz")


if st.button(f"Get cookie {cookie}"):
    getcookie = controller.get(cookie)
    st.write(getcookie)


if st.button("Remove cookie"):
    controller.remove(cookie)


if st.button("Print all cookies"):
    # Get all cookies
    cookies = controller.getAll()
    st.write(cookies)
