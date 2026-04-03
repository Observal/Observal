import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Card } from "@/components/ui";

export function Login() {
  const [key, setKey] = useState("");
  const [error, setError] = useState("");
  const navigate = useNavigate();

  async function handleLogin(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    try {
      const r = await fetch("/api/v1/auth/whoami", { headers: { "X-API-Key": key } });
      if (!r.ok) throw new Error("Invalid API key");
      localStorage.setItem("observal_api_key", key);
      navigate("/");
    } catch {
      setError("Invalid API key. Run 'observal init' to get one.");
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      <Card className="w-full max-w-sm">
        <h1 className="mb-1 text-xl font-bold">Observal</h1>
        <p className="mb-6 text-sm text-muted-foreground">Enter your API key to continue</p>
        <form onSubmit={handleLogin}>
          <input type="password" value={key} onChange={(e) => setKey(e.target.value)} placeholder="API Key"
            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring" />
          {error && <p className="mt-2 text-sm text-destructive">{error}</p>}
          <button type="submit"
            className="mt-4 w-full rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors">
            Login
          </button>
        </form>
      </Card>
    </div>
  );
}
