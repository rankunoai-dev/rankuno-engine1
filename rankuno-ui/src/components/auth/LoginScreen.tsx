import { LockOutlined, UserOutlined } from "@ant-design/icons";
import { Alert, Button, Form, Input } from "antd";
import { useAuthStore } from "../../store/useAuthStore";
import "./login.css";

interface LoginFormValues {
  operator_id: string;
  password: string;
}

/**
 * The unauthenticated landing state.
 *
 * `App` renders this in place of the whole dashboard shell whenever the live
 * engine is reachable and no valid session exists. Since ADR 0016 (session-
 * token authentication), every route past `/auth/login` requires a bearer
 * token, so there is nothing behind this screen that would not immediately
 * answer `401` — gating the shell here, rather than letting each view fail
 * on its own first request, is what turns that into one clear screen instead
 * of a dashboard full of broken panels.
 *
 * No registration link and no "forgot password": `scripts/create_operator.py`
 * is deliberately the only way an operator is provisioned — offline, so an
 * unauthenticated registration route can never exist for anyone to attack —
 * and there is no password-reset flow on the server for this screen to open
 * either.
 */
export function LoginScreen(): JSX.Element {
  const [form] = Form.useForm<LoginFormValues>();
  const login = useAuthStore((state) => state.login);
  const loggingIn = useAuthStore((state) => state.loggingIn);
  const loginError = useAuthStore((state) => state.loginError);

  async function submit(values: LoginFormValues): Promise<void> {
    const ok = await login(values.operator_id, values.password);
    // Cleared only on failure. A rejected password left sitting in the field
    // reads as "try submitting the same thing again"; a cleared one reads
    // correctly as "type it again". On success the screen is about to be
    // replaced by the dashboard, so clearing there would be wasted work.
    if (!ok) form.setFieldValue("password", "");
  }

  return (
    <div className="login-screen">
      <div className="login-card">
        <div className="login-brand">
          <div className="login-mark" aria-hidden="true">
            R
          </div>
          <div>
            <div className="login-title">Rankuno Engine</div>
            <div className="login-subtitle">Sign in to continue</div>
          </div>
        </div>

        {loginError && (
          <Alert type="error" showIcon message={loginError} className="login-alert" />
        )}

        <Form<LoginFormValues>
          form={form}
          layout="vertical"
          requiredMark={false}
          disabled={loggingIn}
          onFinish={(values) => void submit(values)}
        >
          <Form.Item
            name="operator_id"
            label="Operator ID"
            rules={[{ required: true, message: "Enter your operator id." }]}
          >
            <Input
              prefix={<UserOutlined />}
              placeholder="operator id"
              autoComplete="username"
              autoFocus
            />
          </Form.Item>

          <Form.Item
            name="password"
            label="Password"
            rules={[{ required: true, message: "Enter your password." }]}
          >
            <Input.Password
              prefix={<LockOutlined />}
              placeholder="password"
              autoComplete="current-password"
            />
          </Form.Item>

          <Form.Item style={{ marginBottom: 0 }}>
            <Button type="primary" htmlType="submit" loading={loggingIn} block>
              {loggingIn ? "Signing in…" : "Sign in"}
            </Button>
          </Form.Item>
        </Form>
      </div>
    </div>
  );
}
