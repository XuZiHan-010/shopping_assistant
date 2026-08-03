/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 后端 API 基础地址。生产必须显式配置——见 src/api/client.ts。 */
  readonly VITE_API_BASE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
