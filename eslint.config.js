import baseConfig from "./cfg/eslint.config.base.js";

export default [
  ...baseConfig,
  {
    // Templates: feature directories are snake_case to match the
    // DEVENV_<FEATURE> flags, and init files import paths that only exist
    // once they are copied into a project.
    files: ["copy/**", "init/**", "merge/**"],
    rules: {
      "import-x/no-unresolved": "off",
      "unicorn/filename-case": "off",
    },
  },
  {
    files: ["init/**/*.yaml", "init/**/*.yml"],
    rules: {
      "yml/no-empty-document": "off",
      "yml/no-empty-mapping-value": "off",
    },
  },
];
