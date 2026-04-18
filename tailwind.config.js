/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./app/templates/**/*.html",
    "./app/static/js/**/*.js",
    "./app/utils/*.py",
    "./app/services/*.py",
  ],
  theme: {
    extend: {
      fontFamily: {
        // Sets Roboto as the default 'font-sans' across the whole site
        sans: ['Roboto', 'ui-sans-serif', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [],
}