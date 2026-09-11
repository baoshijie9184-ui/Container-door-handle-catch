const fs = require('node:fs')
const path = require('node:path')

const frontendRoot = path.resolve(__dirname, '..', '..')
const projectRoot = path.resolve(frontendRoot, '..')

const readUtf8 = (root, segments) => {
  const filePath = path.join(root, ...segments)
  return fs.readFileSync(filePath, 'utf8')
}

const readFrontendFile = (...segments) => readUtf8(frontendRoot, segments)
const readProjectFile = (...segments) => readUtf8(projectRoot, segments)

module.exports = {
  frontendRoot,
  projectRoot,
  readFrontendFile,
  readProjectFile
}
