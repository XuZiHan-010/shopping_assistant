import { CartClient } from './CartClient'

// 需要会话的页面一律客户端渲染：会话只存浏览器内存，服务端拿不到。
export default function CartPage() {
  return <CartClient />
}
