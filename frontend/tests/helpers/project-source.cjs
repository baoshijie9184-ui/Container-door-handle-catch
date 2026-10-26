const fs = require('node:fs')
const path = require('node:path')
const { pathToFileURL } = require('node:url')

const frontendRoot = path.resolve(__dirname, '..', '..')
const projectRoot = path.resolve(frontendRoot, '..')

const readUtf8 = (root, segments) => {
  const filePath = path.join(root, ...segments)
  return fs.readFileSync(filePath, 'utf8')
}

const readFrontendFile = (...segments) => readUtf8(frontendRoot, segments)
const readProjectFile = (...segments) => readUtf8(projectRoot, segments)
// Keep a real base URL so native ESM resolves the source's dependency graph.
const importFrontendModule = (...segments) => import(pathToFileURL(path.join(frontendRoot, ...segments)).href)

module.exports = {
  frontendRoot,
  projectRoot,
  importFrontendModule,
  readFrontendFile,
  readProjectFile
}
