### Problem

Momentan ist es so, dass die Agenteninfrastruktur, also der Agent Runner, alle entsprechenden Tools und System-Prompts quasi in den Quellcode reingeschrieben werden müssen. Das Gateway wird dann gestartet, was natürlich weniger gut ist, weil ich eigentlich möchte, dass dieses Gateway hier von außen konfigurierbar gemacht werden kann. Das heißt, dass man irgendwie eine Config-File hat, die dann entsprechend den entsprechenden Quellcode bereitstellt, den man von außen implementiert, damit man hier nicht an eine konkrete Implementierung gebunden ist. Zeigt mir im Lösungsansatzsegment bitte mal einen Ansatz, wie man das Ganze entwickeln kann. 

### Solution

#### Ausgangslage

Die Erweiterungsnaht existiert bereits: `AgentRunner` (`agents/contracts.py:113`) ist ein
Protocol, und `AgentThreadService` kennt ausschließlich dieses Protocol. Geschlossen ist
heute nur der Composition Root — `LlmifyAgentProvider` (`container.py:62-78`) verdrahtet
Modell, System-Prompt und `default_tools()` fest, und `default_tools()` (`agents/tools.py`)
importiert die konkreten Tool-Funktionen statisch.

Es fehlt also kein neues Interface, sondern ein **konfigurierbarer Weg von einer
Deklaration zu einer Implementierung**. Das lässt sich in drei Schichten trennen:

1. **Deklaration** — eine Config-Datei beschreibt, *welcher* Agent mit welchen Tools und
   welchem Prompt laufen soll.
2. **Auflösung** — ein Resolver übersetzt Namen aus der Config in Python-Objekte
   (Registry, Entry Points, dotted paths).
3. **Komposition** — ein einziger Dishka-Provider baut daraus den `AgentRunner`.

#### 1. Deklaratives Config-Schema

Neue Datei `gateway/agents/spec.py`. Die Config wird mit Pydantic validiert, bleibt also
im gleichen Stil wie `Settings`:

```python
class ToolSpec(Schema):
    ref: str  # "my_pkg.tools:crm_tools" | "builtin:add_numbers"
    options: dict[str, Any] = Field(default_factory=dict)


class AgentSpec(Schema):
    name: str = "default"
    runner: str = "llmify"  # Registry-Key ODER "my_pkg.runners:build"
    model: str | None = None
    system_prompt: str | None = None
    system_prompt_file: Path | None = None  # entlastet TOML von Multiline-Prompts
    tools: tuple[ToolSpec, ...] = ()
    options: dict[str, Any] = Field(default_factory=dict)  # runner-spezifisch, opak


class RuntimeConfig(Schema):
    default_agent: str = "default"
    agents: tuple[AgentSpec, ...] = (AgentSpec(),)
```

`agent.toml` im Projekt-Root (Pfad über `AGENT_CONFIG` überschreibbar), gelesen mit
`tomllib` aus der Stdlib — keine neue Dependency:

```toml
default_agent = "support"

[[agents]]
name = "support"
runner = "llmify"
model = "gpt-5.4-mini"
system_prompt_file = "prompts/support.md"
tools = [
  { ref = "builtin:add_numbers" },
  { ref = "acme_agents.tools:crm_lookup", options = { base_url = "https://crm.internal" } },
]

[agents.options]
max_tool_rounds = 8
```

Wichtig für die Abgrenzung zu `Settings`: **Secrets bleiben in `Settings`/`.env`.** Die
Config-Datei beschreibt nur Komposition und ist damit committbar. Fehlt die Datei, greifen
die Defaults von `RuntimeConfig` — das heutige Verhalten bleibt also unverändert.

#### 2. Auflösung: Registry + Entry Points + dotted path

Ein `RunnerFactory` ist die eigentliche Erweiterungs-ABI:

```python
class RunnerFactory(Protocol):
    def __call__(self, spec: AgentSpec, settings: Settings) -> AgentRunner: ...


class ToolFactory(Protocol):
    def __call__(self, options: dict[str, Any]) -> Sequence[FunctionTool]: ...
```

Der Resolver kennt drei Quellen, in dieser Reihenfolge:

```python
class Registry:
    def __init__(self) -> None:
        self._runners: dict[str, RunnerFactory] = {}
        self._tools: dict[str, ToolFactory] = {}

    def runner(
        self, name: str
    ) -> Callable[
        [RunnerFactory], RunnerFactory
    ]: ...  # Decorator für In-Process-Registrierung

    def resolve_runner(self, ref: str) -> RunnerFactory:
        if ":" in ref:
            return _load_dotted(ref)  # "acme.runners:build_claude_runner"
        if ref in self._runners:
            return self._runners[ref]
        return _load_entry_point("agent_thread_runtime.runners", ref)
```

- **dotted path** (`modul:attribut`) — der schnellste Weg, ohne Packaging-Zeremonie; für
  Prototypen und projektinterne Runner.
- **Entry Point** (`[project.entry-points."agent_thread_runtime.runners"]`) — der saubere
  Weg für externe Pakete: `pip install acme-agents` genügt, damit `runner = "claude"` in
  der Config funktioniert. Das Gateway kennt das Paket nicht.
- **Registry-Key** — für die mitgelieferten Implementierungen (`llmify`, `fake`).

`_load_dotted` sollte nach dem Import gegen das Protocol prüfen und bei Fehlern eine
klare, konfigurationsbezogene Ausnahme werfen (`ConfigError: agents[0].runner
'acme.runners:build' — module not found`), sonst debuggt man Importfehler im
Lifespan-Stacktrace.

#### 3. Komposition: ein Provider statt zweier

`LlmifyAgentProvider` und `RunnerOverrideProvider` verschwinden zugunsten eines Providers,
der nur noch delegiert:

```python
class AgentProvider(Provider):
    def __init__(self, config: RuntimeConfig, registry: Registry) -> None:
        super().__init__()
        self._config = config
        self._registry = registry

    @provide(scope=Scope.APP)
    def runner(self, settings: Settings) -> AgentRunner:
        spec = self._config.select(self._config.default_agent)
        factory = self._registry.resolve_runner(spec.runner)
        return factory(spec, settings)
```

Und der bisherige `LlmifyAgentProvider`-Inhalt wird selbst nur noch eine registrierte
Factory — er verliert damit seinen Sonderstatus:

```python
@registry.runner("llmify")
def build_llmify_runner(spec: AgentSpec, settings: Settings) -> AgentRunner:
    model = ChatOpenAI(model=spec.model or settings.agent_model, api_key=...)
    tools = tuple(
        chain.from_iterable(registry.resolve_tool(t.ref)(t.options) for t in spec.tools)
    )
    return LlmifyAgentRunner(model, _load_prompt(spec), tools=tools)
```

`create_container(settings, runner=...)` kann als Test-Escape-Hatch bestehen bleiben — der
Override ist dann schlicht die höchste Präzedenz vor der Config. Alternativ wird
`FakeAgentRunner` als `runner = "fake"` registriert, und Tests setzen eine Zwei-Zeilen-Config
statt eines Konstruktor-Arguments.

`create_app` lädt die Config einmal und reicht sie durch:

```python
def create_app(settings=None, config=None, runner=None) -> FastAPI:
    config = config or load_runtime_config(
        Path(os.environ.get("AGENT_CONFIG", "agent.toml"))
    )
```

#### Warum das open/closed ist

Ein neuer Agent-Provider (Anthropic, ein eigener Graph-Runner, ein Remote-Agent hinter
HTTP) erfordert dann: ein externes Paket, das `AgentRunner` implementiert, eine Factory,
einen Entry Point, eine Zeile in `agent.toml`. **Keine Änderung an `gateway/`.** Die
Stabilitätsgarantie liegt genau auf `AgentContext` / `AgentEvent` / `TurnControl` — diese
Typen werden damit zur öffentlichen API und sollten entsprechend versioniert werden.

#### Umsetzungsreihenfolge

1. `AgentSpec` / `RuntimeConfig` + TOML-Loader, mit Defaults die dem heutigen Verhalten
   entsprechen. Noch keine Verhaltensänderung, Tests bleiben grün.
2. `Registry` + `resolve_runner` / `resolve_tool`, `llmify` und `fake` als eingebaute
   Registrierungen. `default_tools()` wird zur Tool-Factory `builtin:add_numbers`.
3. `container.py` auf `AgentProvider` umstellen, die beiden alten Provider entfernen.
4. Entry-Point-Auflösung ergänzen und mit einem Dummy-Paket end-to-end verifizieren.
5. README um einen Abschnitt „Eigenen Agent-Provider anbinden“ erweitern.

#### Offene Entscheidungen

- **Ein Agent pro Prozess oder mehrere?** Das Schema hält bewusst eine Liste von Agents
  bereit. Sobald `thread.create` einen `agent`-Parameter bekommen soll, wird aus der
  `AgentRunner`-Provision eine `AgentRegistry`-Provision (`get(name) -> AgentRunner`) —
  das ist eine Änderung an `AgentThreadService`, deshalb bewusst als zweiter Schritt.
- **Tool-Auflösung pro Turn statt beim Start?** Nötig, sobald Tools von Thread-Kontext
  oder Nutzerrechten abhängen. Dann wandert die Auflösung in einen `ToolResolver`, der dem
  Runner beim `run()` übergeben wird.
- **Prompt-Herkunft.** `system_prompt_file` relativ zur Config-Datei auflösen, nicht zum
  CWD — sonst hängt das Verhalten am Startverzeichnis.
