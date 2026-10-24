/**
 * A thin wrapper around Prism's tokenizer, used only for its string-in /
 * tokens-out API (`Prism.tokenize`), never its HTML-string `highlight()`
 * API. Callers render the returned tokens as ordinary React text children
 * (`<span>{token.text}</span>`), so the model's own code can never reach
 * the DOM as parsed HTML -- see DECISIONS.md D-081.
 */

import Prism from "prismjs";
import "prismjs/components/prism-python";

export interface CodeToken {
  text: string;
  className: string;
}

type TokenContent = string | Prism.Token | (string | Prism.Token)[];

function flattenContent(content: TokenContent, className: string): CodeToken[] {
  if (typeof content === "string") {
    return [{ text: content, className }];
  }
  if (Array.isArray(content)) {
    return content.flatMap((item) => flattenOne(item, className));
  }
  return flattenOne(content, className);
}

function flattenOne(token: string | Prism.Token, parentClassName: string): CodeToken[] {
  if (typeof token === "string") {
    return [{ text: token, className: parentClassName }];
  }
  return flattenContent(token.content as TokenContent, `token-${token.type}`);
}

/** Tokenize Python source. The concatenation of every token's `text` always
 * exactly reconstructs `code` -- nothing is dropped or altered. */
export function tokenizePython(code: string): CodeToken[] {
  const tokens = Prism.tokenize(code, Prism.languages.python) as (string | Prism.Token)[];
  return tokens.flatMap((token) => flattenOne(token, "token-plain"));
}
