/**
 * Vite entrypoint.  Wires up the design tokens stylesheet, mounts the App.
 */

import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./styles/tokens.css";
import "./styles/print.css";

const root = document.getElementById("root");
if (!root) throw new Error("missing #root element");
ReactDOM.createRoot(root).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
