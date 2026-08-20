import { env } from "cloudflare:workers";
import { drizzle } from "drizzle-orm/d1";
import * as schema from "./schema";

type Bindings = { DB?: D1Database };

export function getDb() {
  // La plataforma inyecta el binding a través de la configuración de hosting;
  // el paquete de tipos no puede conocer el nombre específico de este proyecto.
  const bindings = env as unknown as Bindings;
  if (!bindings.DB) {
    throw new Error(
      "Cloudflare D1 binding `DB` is unavailable. Set the `d1` field in .openai/hosting.json to `DB` or let your control plane inject the real binding values before using the database."
    );
  }

  return drizzle(bindings.DB, { schema });
}
