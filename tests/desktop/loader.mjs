// Resolve the three specifiers Hermes provides to small stand-ins, so plugin.js can be imported
// by Node's test runner without Hermes.
const stubs = {
  '@hermes/plugin-sdk': 'export const host = { navigate() {}, state: {} }; export const Button = () => null; export const SandboxedFrame = () => null; export const ROUTES_AREA = "routes"; export const SIDEBAR_NAV_AREA = "nav"; export const TRANSCRIPT_DIRECTIVE_AREA = "directive"',
  react: 'export const useCallback = f => f; export const useEffect = () => {}; export const useRef = v => ({ current: v }); export const useState = v => [v, () => {}]',
  'react/jsx-runtime': 'export const jsx = () => null; export const jsxs = () => null'
}
export async function resolve(specifier, context, next) {
  if (specifier in stubs) return { url: 'data:text/javascript,' + encodeURIComponent(stubs[specifier]), shortCircuit: true }
  return next(specifier, context)
}
