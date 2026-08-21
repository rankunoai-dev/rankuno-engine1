import { App as AntApp, ConfigProvider, theme } from "antd";
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";

const root = document.getElementById("root");
if (!root) throw new Error("#root is missing from index.html");

ReactDOM.createRoot(root).render(
  <React.StrictMode>
    {/*
      antd is themed to match `design-system.css`, not to its own taste.

      It ran on `darkAlgorithm` while the design system is a light palette, so
      every antd surface painted a dark island inside a white dashboard — the
      crawl-jobs table was black rows under a white header, and `jobs.css` and
      `audit.css` had each grown a private set of light-on-dark text tokens to
      stay readable inside it. Two themes, and a widening pile of code to
      reconcile them at the edges.

      The tokens below are the design system's own variables, spelled out
      because `ConfigProvider` takes values rather than `var()` references.
      They must be kept in step with `:root` in `design-system.css`.
    */}
    <ConfigProvider
      theme={{
        algorithm: theme.defaultAlgorithm,
        token: {
          colorPrimary: "#1677ff",
          colorInfo: "#1677ff",
          colorBgBase: "#f5f6f8",
          colorBgContainer: "#ffffff",
          colorBgElevated: "#ffffff",
          colorBorder: "#e6e9ef",
          colorText: "#1d2635",
          colorTextSecondary: "#5c6b83",
          colorTextTertiary: "#98a4b8",
          borderRadius: 8,
          fontSize: 13,
        },
        components: {
          Tree: { nodeSelectedBg: "#e6f4ff", nodeHoverBg: "#f5f6f8" },
          Drawer: { colorBgElevated: "#ffffff" },
        },
      }}
    >
      <AntApp>
        <App />
      </AntApp>
    </ConfigProvider>
  </React.StrictMode>,
);
