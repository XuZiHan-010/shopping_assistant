#!/usr/bin/env node
/** 把商家端的设计 token 与品牌 logo 同步成 shop/ 的提交副本（构建上下文里没有 ../frontend）。 */
import { copyFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(fileURLToPath(new URL('..', import.meta.url)))
const frontend = resolve(root, '..', 'frontend')

copyFileSync(resolve(frontend, 'src/assets/tokens.css'), resolve(root, 'src/styles/tokens.css'))
copyFileSync(resolve(frontend, 'public/borough-logo.svg'), resolve(root, 'public/borough-logo.svg'))
console.log('已同步 tokens.css 与 borough-logo.svg')
