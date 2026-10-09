import { App as AntApp } from "antd";
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";
import { ThemedConfigProvider } from "./ThemedConfigProvider";

const root = document.getElementById("root");
if (!root) throw new Error("#root is missing from index.html");

ReactDOM.createRoot(root).render(
  <React.StrictMode>
    <ThemedConfigProvider>
      <AntApp>
        <App />
      </AntApp>
    </ThemedConfigProvider>
  </React.StrictMode>,
);
