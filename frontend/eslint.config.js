import js from '@eslint/js'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'

export default [
  { ignores: ['dist', '../static/app'] },
  js.configs.recommended,
  {
    files: ['src/**/*.{ts,tsx}'],
    languageOptions: { ecmaVersion: 2022, sourceType: 'module', parser: tseslint.parser },
    plugins: { '@typescript-eslint': tseslint.plugin, 'react-hooks': reactHooks, 'react-refresh': reactRefresh },
    rules: {
      ...reactHooks.configs['recommended-latest'].rules,
      ...reactRefresh.configs.vite.rules,
      // TypeScript owns unresolved type names; the base JS rules otherwise flag
      // browser and DOM types that are deliberately supplied by tsconfig's lib.
      'no-undef': 'off',
      'no-unused-vars': 'off',
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
      // This is an application entry module, not a component library. Route
      // exports are intentional, and settings are hydrated from the server.
      'react-refresh/only-export-components': 'off',
      'react-hooks/set-state-in-effect': 'off',
      // TanStack Virtual intentionally exposes imperative measurement methods.
      'react-hooks/incompatible-library': 'off',
    },
  },
]
