import { notFound } from 'next/navigation'
import { ApiError } from '@/api/errors'

/** 公开页面的服务端数据读取：未知或未开放的店铺/商品统一 403，一律渲染成同一个「不存在」。 */
export async function orNotFound<T>(load: () => Promise<T>): Promise<T> {
  try {
    return await load()
  } catch (error) {
    if (error instanceof ApiError && (error.status === 403 || error.status === 404)) notFound()
    throw error
  }
}
