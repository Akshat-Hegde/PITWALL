// vite.config.ts runs in Node; @types/node isn't installed, so declare the two calls it makes.
declare module "node:fs" {
  export function readFileSync(path: string, encoding: "utf-8"): string;
}
declare module "node:url" {
  export function fileURLToPath(url: URL | string): string;
}
