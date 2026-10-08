/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 后端 API 基础地址。生产必须显式配置——见 src/api/client.ts。 */
  readonly VITE_API_BASE_URL?: string
  /** 是否启用 Mock 传输层。F2 演示用；F3 接入真实 API 后置为 false——见 src/api/transport.ts。 */
  readonly VITE_USE_MOCK?: string
  /** 只读管理令牌的构建期镜像（可选）——见 src/api/client.ts。 */
  readonly VITE_VIEWER_TOKEN?: string
  /** 顾客端地址（可选）。配置后外壳显示「顾客视角」入口——见 src/api/client.ts。 */
  readonly VITE_SHOP_BASE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
