import { App as AntApp, ConfigProvider, theme } from "antd";
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";
import { token } from "./styles/tokens";

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

      `ConfigProvider` takes values rather than `var()` references, so the
      palette has to be spelled out a second time here. It used to be spelled
      out as literals under a comment asking the next reader to keep them in
      step with `:root` by hand. The values were in fact still correct; a
      request is simply not a mechanism, and this is the one duplicate of the
      palette that no reviewer can catch by reading either file alone.

      `styles/tokens.ts` is the mirror, and `styles/tokens.test.ts` parses
      `design-system.css` and fails if any value below stops matching the token
      it is named by. The stylesheet remains the one place a colour is chosen.
    */}
    <ConfigProvider
      theme={{
        algorithm: theme.defaultAlgorithm,
        token: {
          colorPrimary: token("--primary"),
          // antd derives its own hover from `colorPrimary` by lightening it,
          // which on a fill carrying white text moves the wrong way: #df212a is
          // 4.79:1 under white and anything lighter drops below AA. Both states
          // are pinned to darker shades instead.
          colorPrimaryHover: token("--primary-hover"),
          colorPrimaryActive: token("--primary-hover"),
          colorInfo: token("--primary"),
          // Seeds, and antd generates a ten-step ramp from each. The seeds have
          // to be dark enough to pass as text, which makes the pale end of the
          // generated ramp muddy rather than pale, so the three surfaces antd
          // takes off that end are pinned instead of derived.
          colorError: token("--danger"),
          colorErrorBg: token("--danger-bg"),
          colorErrorBorder: token("--danger-line"),
          colorSuccess: token("--ok"),
          colorSuccessBg: token("--ok-bg"),
          colorSuccessBorder: token("--ok-line"),
          colorWarning: token("--warn"),
          colorWarningBg: token("--warn-bg"),
          colorWarningBorder: token("--warn-line"),
          colorBgBase: token("--bg"),
          colorBgContainer: token("--panel"),
          colorBgElevated: token("--panel"),
          colorBorder: token("--line"),
          colorText: token("--ink"),
          colorTextSecondary: token("--dim"),
          colorTextTertiary: token("--faint"),
          borderRadius: 4,
          fontFamily: token("--sans"),
          fontSize: 13,
        },
        components: {
          Tree: { nodeSelectedBg: token("--primary-bg"), nodeHoverBg: token("--bg") },
          Drawer: { colorBgElevated: token("--panel") },
        },
      }}
    >
      <AntApp>
        <App />
      </AntApp>
    </ConfigProvider>
  </React.StrictMode>,
);
