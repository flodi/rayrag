import { Action, ActionPanel, Color, Icon, List, getPreferenceValues } from "@raycast/api";
import { useFetch } from "@raycast/utils";
import { useState } from "react";

interface Preferenze {
  endpoint: string;
  quanti: string;
}

interface Risultato {
  path: string;
  nome: string;
  cartella: string;
  punteggio: number;
  frammento: string;
  copie?: number; // copie identiche dello stesso documento, collassate dal servizio
}

interface Risposta {
  query: string;
  risultati: Risultato[];
}

/** Il servizio gira su localhost: se non risponde, l'errore va mostrato, non nascosto. */
const AVVIO = "python servizio/servizio.py";

export default function Cerca() {
  const preferenze = getPreferenceValues<Preferenze>();
  const endpoint = (preferenze.endpoint || "http://127.0.0.1:8787").replace(/\/$/, "");
  const quanti = Number(preferenze.quanti) || 12;

  const [query, setQuery] = useState("");
  const cercabile = query.trim().length > 1;

  const { data, isLoading, error } = useFetch<Risposta>(
    `${endpoint}/cerca?q=${encodeURIComponent(query.trim())}&n=${quanti}`,
    {
      execute: cercabile,
      keepPreviousData: true, // evita che la lista sfarfalli fra un tasto e l'altro
    },
  );

  const risultati = data?.risultati ?? [];

  return (
    <List
      isLoading={isLoading}
      onSearchTextChange={setQuery}
      searchBarPlaceholder="contratti con nordvela"
      throttle
    >
      {error ? (
        <List.EmptyView
          icon={{ source: Icon.Plug, tintColor: Color.Red }}
          title="Servizio di ricerca non raggiungibile"
          description={`Nessuna risposta da ${endpoint}. Avvialo e riprova.`}
          actions={
            <ActionPanel>
              <Action.CopyToClipboard title="Copia Il Comando Di Avvio" content={AVVIO} />
            </ActionPanel>
          }
        />
      ) : !cercabile ? (
        <List.EmptyView
          icon={Icon.MagnifyingGlass}
          title="Cerca per significato"
          description="Descrivi il documento invece di indovinarne le parole: «cosa devo pagare al fisco» trova gli F24."
        />
      ) : (
        <List.Section
          title={risultati.length > 0 ? "Risultati" : undefined}
          subtitle={risultati.length > 0 ? `${risultati.length}` : undefined}
        >
          {risultati.map((r) => (
            <List.Item
              key={r.path}
              icon={{ fileIcon: r.path }}
              title={r.nome}
              subtitle={r.frammento}
              accessories={[
                ...(r.copie
                  ? [{ text: `${r.copie + 1} copie`, tooltip: "Lo stesso file esiste in più cartelle" }]
                  : []),
                { text: r.punteggio.toFixed(2), tooltip: `Similarità: ${r.punteggio}` },
              ]}
              actions={
                <ActionPanel>
                  <Action.Open title="Apri" target={r.path} />
                  <Action.ShowInFinder path={r.path} />
                  <Action.CopyToClipboard
                    title="Copia Percorso"
                    content={r.path}
                    shortcut={{ modifiers: ["cmd", "shift"], key: "c" }}
                  />
                  <Action.OpenWith path={r.path} shortcut={{ modifiers: ["cmd"], key: "o" }} />
                </ActionPanel>
              }
            />
          ))}
        </List.Section>
      )}
    </List>
  );
}
