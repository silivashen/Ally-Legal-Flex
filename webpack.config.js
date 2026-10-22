/* eslint-disable no-undef */

const devCerts = require("office-addin-dev-certs");
const CopyWebpackPlugin = require("copy-webpack-plugin");
const HtmlWebpackPlugin = require("html-webpack-plugin");

async function getHttpsOptions() {
  const httpsOptions = await devCerts.getHttpsServerOptions();
  return { ca: httpsOptions.ca, key: httpsOptions.key, cert: httpsOptions.cert };
}

module.exports = async (env, options) => {
  const config = {
    devtool: "source-map",
    entry: {
      polyfill: ["core-js/stable", "regenerator-runtime/runtime"],
      taskpane: ["./src/taskpane/taskpane.js", "./src/taskpane/taskpane.html"],
      configpane: ["./src/configpane/configpane.js", "./src/configpane/configpane.html"],
      commands: "./src/commands/commands.js",
    },
    output: {
      clean: true,
    },
    resolve: {
      extensions: [".html", ".js"],
    },
    module: {
      rules: [
        {
          test: /\.js$/,
          exclude: /node_modules/,
          use: {
            loader: "babel-loader",
            options: {
              presets: ["@babel/preset-env"],
            },
          },
        },
        {
          test: /\.html$/,
          exclude: /node_modules/,
          use: "html-loader",
        },
        {
          test: /\.(png|jpg|jpeg|gif|ico|json)$/,
          type: "asset/resource",
          generator: {
            filename: "assets/[name][ext][query]",
          },
        },
        {
          test: /\.json$/,
          type: 'json',
          use: 'json-loader' // This loader is often not needed; Webpack can handle JSON natively.
        }
      ],
    },
    plugins: [
      new HtmlWebpackPlugin({
        filename: "taskpane.html",
        template: "./src/taskpane/taskpane.html",
        chunks: ["polyfill", "taskpane"],
      }),
      new HtmlWebpackPlugin({
        filename: "configpane.html",
        template: "./src/configpane/configpane.html",
        chunks: ["polyfill", "configpane"],
      }),

      new HtmlWebpackPlugin({
        filename: "commands.html",
        template: "./src/commands/commands.html",
        chunks: ["polyfill", "commands"],
      }),

      new CopyWebpackPlugin({
        patterns: [
          {
            from: "assets/*",
            to: "assets/[name][ext][query]",
          },
          {
            from: "package.json",
            to: "package.json",
          },
          {
            from: "manifest*.xml",
            to: "[name]" + "[ext]",
          },
          {
            from: "src/help.html",
            to: "help.html",
          },
          {
            from: "USER_GUIDE.zh-CN.md",
            to: "USER_GUIDE.zh-CN.md",
          },
          {
            from: "docs/images/user-guide/*.jpg",
            to: "docs/images/user-guide/[name][ext]",
          },
          {
            from: "docs/examples/Ally-Legal-Flex-demo.docx",
            to: "docs/examples/Ally-Legal-Flex-demo.docx",
          },

          {
            from: 'src/config/*.json', 
            to: "assets/[name][ext][query]",
          },

        ],
      }),

    ],
    devServer: {
      host: "127.0.0.1",
      allowedHosts: ["localhost", "127.0.0.1", "[::1]"],
      server: {
        type: "https",
        options: env.WEBPACK_BUILD || options.https !== undefined ? options.https : await getHttpsOptions(),
      },
      port: process.env.npm_package_config_dev_server_port || 3000,
      proxy: [
        {
          context: ["/local-api/flow"],
          target: "http://127.0.0.1:8083",
          pathRewrite: { "^/local-api/flow": "" },
          // Summary/review may take longer than a typical page request.
          proxyTimeout: 600000,
        },
        {
          context: ["/local-api/policy"],
          target: "http://127.0.0.1:8084",
          pathRewrite: { "^/local-api/policy": "" },
        },
        {
          context: ["/local-api/model"],
          target: "http://127.0.0.1:8085",
          pathRewrite: { "^/local-api/model": "" },
        },
      ],
    },
  };

  return config;
};
