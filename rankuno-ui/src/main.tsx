import { App as AntApp, ConfigProvider, theme } from "antd";
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";

const root = document.getElementById("root");
if (!root) throw new Error("#root is missing from index.html");

ReactDOM.createRoot(root).render(
  <React.StrictMode>
    <ConfigProvider
      theme={{
        algorithm: theme.darkAlgorithm,
        token: {
          colorPrimary: "#00f2fe",
          colorInfo: "#00f2fe",
          colorBgBase: "#0a0d14",
          colorBgContainer: "#0f1420",
          colorBgElevated: "#131823",
          colorBorder: "#1e293b",
          borderRadius: 8,
          fontSize: 13,
        },
        components: {
          Tree: { nodeSelectedBg: "#00f2fe22", nodeHoverBg: "#ffffff0a" },
          Drawer: { colorBgElevated: "#0f1420" },
        },
      }}
    >
      <AntApp>
        <App />
      </AntApp>
    </ConfigProvider>
  </React.StrictMode>,
);
