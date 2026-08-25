/// <reference types="@raycast/api">

/* 🚧 🚧 🚧
 * This file is auto-generated from the extension's manifest.
 * Do not modify manually. Instead, update the `package.json` file.
 * 🚧 🚧 🚧 */

/* eslint-disable @typescript-eslint/ban-types */

type ExtensionPreferences = {
  /** Servizio di ricerca - Indirizzo del servizio RayRAG in ascolto su localhost */
  "endpoint": string,
  /** Risultati - Quanti file mostrare */
  "quanti": string
}

/** Preferences accessible in all the extension's commands */
declare type Preferences = ExtensionPreferences

declare namespace Preferences {
  /** Preferences accessible in the `cerca` command */
  export type Cerca = ExtensionPreferences & {}
}

declare namespace Arguments {
  /** Arguments passed to the `cerca` command */
  export type Cerca = {}
}

