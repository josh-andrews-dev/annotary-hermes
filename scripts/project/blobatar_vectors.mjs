// Regenerates tests/fixtures/blobatar_vectors.json from a real blobatar release, the one Hermes
// Desktop ships: node scripts/project/blobatar_vectors.mjs <extracted npm package> > the fixture
import { pathToFileURL } from 'node:url'
import { readFileSync } from 'node:fs'

const pkg = process.argv[2]
const meta = JSON.parse(readFileSync(`${pkg}/package.json`, 'utf8'))
const entry = meta.exports['./blob']
const { blobatar } = await import(pathToFileURL(`${pkg}/${typeof entry === 'string' ? entry : entry.default}`).href)
// BLOB_KIND_TRAIT in Hermes Desktop's avatar.tsx.
const kinds = {
  round: 0.11, organic: 0.35, boxy: 0.54, capsule: 0.65, nub: 0.745,
  cloud: 0.825, droplet: 0.8875, hexagon: 0.9325, sun: 0.965, triangle: 0.99
}
const seeds = ['coder', 'default', 'Mixed Case', ' spaced ']
for (let i = 0; i < 24; i++) seeds.push(`bot-${i.toString(36)}`)
const vectors = seeds.map(seed => ({ seed, kind: '', svg: blobatar(seed, { size: 64 }) }))
for (const kind in kinds) {
  for (let i = 0; i < 2; i++) {
    const seed = `k${i}`
    vectors.push({ seed, kind, svg: blobatar(seed, { size: 64, traits: { shape: kinds[kind] } }) })
  }
}
console.log(JSON.stringify({ version: meta.version, vectors }, null, 0))
