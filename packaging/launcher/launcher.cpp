// Morpho.exe: abre o app.
//
// O app e escrito em Python; este programa carrega o Python que vem no pacote
// (pasta "python", ao lado deste arquivo) dentro do proprio processo e manda
// rodar a janela (o modulo app.ui). Assim o que aparece na barra de tarefas e
// no Gerenciador de Tarefas e "Morpho", com o icone do app, e fixar na barra
// de tarefas funciona como em qualquer programa.
//
// Nada e instalado nem alterado no sistema por este programa.

#include <windows.h>
#include <shellapi.h>
#include <string>
#include <vector>

typedef int (*PyMainFunction)(int, wchar_t **);

static int Fail(const std::wstring &text)
{
	MessageBoxW(NULL, text.c_str(), L"Morpho", MB_OK | MB_ICONERROR);
	return 1;
}

int WINAPI wWinMain(HINSTANCE, HINSTANCE, PWSTR, int)
{
	wchar_t self[MAX_PATH * 4];
	DWORD length = GetModuleFileNameW(NULL, self, sizeof(self) / sizeof(*self));
	if (!length || length >= sizeof(self) / sizeof(*self)) return Fail(L"Não consegui descobrir onde o Morpho está instalado.");
	std::wstring root(self);
	root.erase(root.find_last_of(L"\\/"));
	const std::wstring python = root + L"\\python";

	if (GetFileAttributesW((python + L"\\python312.dll").c_str()) == INVALID_FILE_ATTRIBUTES)
		return Fail(L"Faltam arquivos do Morpho (a pasta “python” não foi encontrada em\n" + root + L").\n\nInstale o Morpho de novo.");

	// O Python do pacote, isolado de qualquer outro Python do computador.
	SetEnvironmentVariableW(L"PYTHONHOME", python.c_str());
	SetEnvironmentVariableW(L"PYTHONPATH", root.c_str());
	SetEnvironmentVariableW(L"PYTHONNOUSERSITE", L"1");
	SetEnvironmentVariableW(L"PYTHONDONTWRITEBYTECODE", NULL);
	SetCurrentDirectoryW(root.c_str());

	// As bibliotecas do Python ficam na pasta dele, nao ao lado deste programa: a pasta entra
	// na busca de DLLs, e as duas que outros modulos procuram pelo nome ja ficam carregadas.
	SetDllDirectoryW(python.c_str());
	AddDllDirectory(python.c_str());
	HMODULE library = LoadLibraryExW((python + L"\\python312.dll").c_str(), NULL, LOAD_WITH_ALTERED_SEARCH_PATH);
	if (!library) return Fail(L"Não consegui carregar o Python do Morpho (python312.dll).");
	LoadLibraryExW((python + L"\\python3.dll").c_str(), NULL, LOAD_WITH_ALTERED_SEARCH_PATH);
	PyMainFunction PyMain = (PyMainFunction)GetProcAddress(library, "Py_Main");
	if (!PyMain) return Fail(L"O Python do Morpho está incompleto (Py_Main não encontrado).");

	// Morpho.exe <opcoes>  ->  python -m app.ui <opcoes>
	int count = 0;
	wchar_t **given = CommandLineToArgvW(GetCommandLineW(), &count);
	std::vector<wchar_t *> arguments;
	arguments.push_back(self);
	arguments.push_back(const_cast<wchar_t *>(L"-m"));
	arguments.push_back(const_cast<wchar_t *>(L"app.ui"));
	for (int i = 1; given && i < count; i++) arguments.push_back(given[i]);
	arguments.push_back(NULL);
	return PyMain((int)arguments.size() - 1, arguments.data());
}
