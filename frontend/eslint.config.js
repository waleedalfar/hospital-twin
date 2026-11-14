import js from '@eslint/js';
import reactHooks from 'eslint-plugin-react-hooks';
import globals from 'globals';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  { ignores: ['src/state/wsTypes.ts', 'scripts', 'dist', 'coverage', 'node_modules', 'playwright-report', 'test-results'] },
  js.configs.recommended,
  ...tseslint.configs.strictTypeChecked,
  {
    languageOptions: {
      globals: { ...globals.browser, ...globals.node },
      parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname },
    },
    plugins: { 'react-hooks': reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      '@typescript-eslint/no-explicit-any': 'error',
      '@typescript-eslint/restrict-template-expressions': ['error', { allowNumber: true }],
    },
  },
  {
    // Tests assert on data they have just built; a failed `!` is a failed test, which is the point.
    files: ['tests/**', 'e2e/**'],
    rules: { '@typescript-eslint/no-non-null-assertion': 'off', '@typescript-eslint/no-confusing-void-expression': 'off' },
  },
  // Shorthand arrow bodies that call a setter are the clearest form in the render code.
  { files: ['src/engine/**'], rules: { '@typescript-eslint/no-confusing-void-expression': ['error', { ignoreArrowShorthand: true }] } },
  { files: ['eslint.config.js'], ...tseslint.configs.disableTypeChecked },
);
