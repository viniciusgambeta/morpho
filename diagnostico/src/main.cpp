// Morpho Diagnostico: diz se este computador roda o Morpho, da uma nota e, se a
// pessoa quiser, baixa o instalador.
//
//   MorphoDiagnostico.exe                 abre a janela
//   MorphoDiagnostico.exe --json ARQ      grava o resultado em ARQ e sai (testes)
//   MorphoDiagnostico.exe --shot ARQ.png  grava a imagem da janela e sai (testes, capturas)
//       --fake CENARIO                    resultado inventado: referencia, top, fraco, sem-nvidia
//       --progress 0.42                   mostra a tela de download nessa fracao
//       --manifest URL                    lista de arquivos do instalador (padrao: a do site)
//
// Nada e instalado nem alterado no computador pelo diagnostico. O download, quando
// pedido, vai para a pasta Downloads\Morpho.

#include "probe.h"
#include "site.h"

#include <windowsx.h>
#include <objidl.h>
#include <gdiplus.h>
#include <dwmapi.h>
#include <shellapi.h>
#include <shlobj.h>
#include <wininet.h>
#include <bcrypt.h>
#include <algorithm>
#include <cmath>

using namespace Gdiplus;

// ---- cores e medidas (as mesmas do app) ---------------------------------------------------
static const Color WINDOW(255, 14, 16, 20), CARD(255, 26, 30, 38), BORDER(255, 38, 43, 55), FIELD(255, 35, 40, 52);
static const Color INK(255, 233, 235, 241), MUTED(255, 152, 161, 179), FAINT(255, 107, 115, 133);
static const Color ACCENT(255, 124, 156, 255), GO(255, 34, 197, 94), GO_HOVER(255, 46, 212, 107);
static const Color STOP(255, 239, 68, 68), AMBER(255, 245, 180, 83);
static const int WIDTH = 860;   // largura util da janela, em pixels logicos

// ---- estado -------------------------------------------------------------------------------
enum Stage { READY, LISTING, DOWNLOADING, CHECKING, DONE, BROKEN };

struct Item
{
	std::wstring name, url, sha256;
	ULONGLONG size = 0;
};

static Report g_report;
static HWND g_window;
static HICON g_icon;
static double g_scale = 1.0;
static std::wstring g_manifest = SITE_URL L"/download.json";

static CRITICAL_SECTION g_lock;
static Stage g_stage = READY;
static volatile LONG g_cancel = 0;
static ULONGLONG g_total = 0, g_received = 0;
static int g_file = 0, g_files = 0;
static std::wstring g_error, g_setup, g_folder;
static std::wstring g_autoResult;       // modo de teste (--auto-download ARQ): onde gravar o desfecho
static std::wstring g_folderOverride;   // modo de teste (--folder PASTA): no lugar de Downloads
static double g_speed = 0;              // bytes por segundo, suavizado
static ULONGLONG g_lastBytes = 0;
static DWORD g_lastTick = 0;

enum Button { NONE, PRIMARY, SECONDARY };
static RECT g_primary, g_secondary;
static Button g_hover = NONE, g_pressed = NONE;

// ---- utilidades ---------------------------------------------------------------------------
static std::wstring Bytes(ULONGLONG bytes)
{
	wchar_t text[64];
	if (bytes >= GB) swprintf_s(text, L"%.1f GB", (double)bytes / GB);
	else swprintf_s(text, L"%.0f MB", (double)bytes / (1024.0 * 1024.0));
	std::wstring out(text);
	std::replace(out.begin(), out.end(), L'.', L',');
	return out;
}

static std::wstring Wide(const std::string &utf8)
{
	if (utf8.empty()) return L"";
	const int length = MultiByteToWideChar(CP_UTF8, 0, utf8.data(), (int)utf8.size(), NULL, 0);
	std::wstring out(length, 0);
	MultiByteToWideChar(CP_UTF8, 0, utf8.data(), (int)utf8.size(), &out[0], length);
	return out;
}

static std::string Utf8(const std::wstring &wide)
{
	if (wide.empty()) return "";
	const int length = WideCharToMultiByte(CP_UTF8, 0, wide.data(), (int)wide.size(), NULL, 0, NULL, NULL);
	std::string out(length, 0);
	WideCharToMultiByte(CP_UTF8, 0, wide.data(), (int)wide.size(), &out[0], length, NULL, NULL);
	return out;
}

static void WriteFileText(const std::wstring &path, const std::wstring &text)
{
	HANDLE file = CreateFileW(path.c_str(), GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
	if (file == INVALID_HANDLE_VALUE) return;
	const std::string bytes = Utf8(text);
	DWORD written;
	WriteFile(file, bytes.data(), (DWORD)bytes.size(), &written, NULL);
	CloseHandle(file);
}

static void SetStage(Stage stage, const std::wstring &error = L"")
{
	EnterCriticalSection(&g_lock);
	g_stage = stage;
	if (!error.empty()) g_error = error;
	LeaveCriticalSection(&g_lock);
	if (g_window) PostMessageW(g_window, WM_APP, 0, 0);
}

// ---- download -----------------------------------------------------------------------------
// A lista do que baixar fica no site (download.json): nome, endereco, tamanho e a impressao
// digital (SHA-256) de cada arquivo. Assim o lugar onde os arquivos grandes ficam hospedados
// pode mudar sem trocar este programa.

static std::wstring Field(const std::wstring &object, const wchar_t *key)
{
	const std::wstring quoted = std::wstring(L"\"") + key + L"\"";
	size_t at = object.find(quoted);
	if (at == std::wstring::npos) return L"";
	at = object.find(L':', at + quoted.size());
	if (at == std::wstring::npos) return L"";
	at++;
	while (at < object.size() && iswspace(object[at])) at++;
	if (at < object.size() && object[at] == L'"')
	{
		const size_t end = object.find(L'"', at + 1);
		return end == std::wstring::npos ? L"" : object.substr(at + 1, end - at - 1);
	}
	size_t end = at;
	while (end < object.size() && iswdigit(object[end])) end++;
	return object.substr(at, end - at);
}

static bool HttpText(HINTERNET session, const std::wstring &url, std::string &out)
{
	HINTERNET request = InternetOpenUrlW(session, url.c_str(), NULL, 0,
										 INTERNET_FLAG_RELOAD | INTERNET_FLAG_NO_CACHE_WRITE | INTERNET_FLAG_NO_UI, 0);
	if (!request) return false;
	DWORD status = 0, size = sizeof(status);
	HttpQueryInfoW(request, HTTP_QUERY_STATUS_CODE | HTTP_QUERY_FLAG_NUMBER, &status, &size, NULL);
	char buffer[8192];
	DWORD got = 0;
	while (status == 200 && InternetReadFile(request, buffer, sizeof(buffer), &got) && got) out.append(buffer, got);
	InternetCloseHandle(request);
	return status == 200 && !out.empty();
}

// Devolve se conseguiu ler a lista; ela pode vir vazia (instalador ainda nao publicado).
static bool ReadList(HINTERNET session, std::vector<Item> &items)
{
	std::string body;
	if (!HttpText(session, g_manifest, body)) return false;
	const std::wstring text = Wide(body);
	size_t at = text.find(L"\"files\"");
	if (at == std::wstring::npos) return false;
	const size_t stop = text.find(L']', at);
	while (true)
	{
		const size_t open = text.find(L'{', at);
		if (open == std::wstring::npos || open > stop) break;
		const size_t close = text.find(L'}', open);
		if (close == std::wstring::npos) break;
		const std::wstring object = text.substr(open, close - open + 1);
		Item item;
		item.name = Field(object, L"name");
		item.url = Field(object, L"url");
		item.sha256 = Field(object, L"sha256");
		item.size = _wcstoui64(Field(object, L"size").c_str(), NULL, 10);
		// Nome simples, sem caminho: o arquivo vai sempre para a pasta de download.
		const bool safe = item.url.compare(0, 8, L"https://") == 0 || item.url.compare(0, 17, L"http://127.0.0.1:") == 0;   // o segundo, so em testes
		if (!item.name.empty() && item.name.find_first_of(L"\\/:") == std::wstring::npos && safe && item.size)
			items.push_back(item);
		at = close + 1;
	}
	return true;
}

static ULONGLONG FileSize(const std::wstring &path)
{
	WIN32_FILE_ATTRIBUTE_DATA data;
	if (!GetFileAttributesExW(path.c_str(), GetFileExInfoStandard, &data)) return 0;
	return ((ULONGLONG)data.nFileSizeHigh << 32) | data.nFileSizeLow;
}

static std::wstring Sha256(const std::wstring &path)
{
	BCRYPT_ALG_HANDLE algorithm = NULL;
	BCRYPT_HASH_HANDLE hash = NULL;
	std::wstring out;
	HANDLE file = CreateFileW(path.c_str(), GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, FILE_FLAG_SEQUENTIAL_SCAN, NULL);
	if (file == INVALID_HANDLE_VALUE) return out;
	if (BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, NULL, 0) == 0 &&
		BCryptCreateHash(algorithm, &hash, NULL, 0, NULL, 0, 0) == 0)
	{
		std::vector<BYTE> buffer(1 << 20);
		DWORD got = 0;
		bool ok = true;
		while (ok && ReadFile(file, buffer.data(), (DWORD)buffer.size(), &got, NULL) && got)
		{
			ok = BCryptHashData(hash, buffer.data(), got, 0) == 0 && !g_cancel;
			EnterCriticalSection(&g_lock);
			g_received += got;
			LeaveCriticalSection(&g_lock);
		}
		BYTE digest[32];
		if (ok && BCryptFinishHash(hash, digest, sizeof(digest), 0) == 0)
			for (BYTE b : digest)
			{
				wchar_t hex[3];
				swprintf_s(hex, L"%02x", b);
				out += hex;
			}
	}
	if (hash) BCryptDestroyHash(hash);
	if (algorithm) BCryptCloseAlgorithmProvider(algorithm, 0);
	CloseHandle(file);
	return out;
}

// Baixa um arquivo, continuando de onde parou se ja houver um pedaco dele na pasta.
static bool Fetch(HINTERNET session, const Item &item, const std::wstring &target, std::wstring &error)
{
	const std::wstring partial = target + L".parte";
	for (int attempt = 0; attempt < 4 && !g_cancel; attempt++)
	{
		ULONGLONG have = FileSize(partial);
		if (have > item.size)
		{
			DeleteFileW(partial.c_str());
			have = 0;
		}
		if (have < item.size)
		{
			wchar_t range[64];
			swprintf_s(range, L"Range: bytes=%llu-\r\n", have);
			HINTERNET request = InternetOpenUrlW(session, item.url.c_str(), have ? range : NULL, have ? (DWORD)-1 : 0,
												 INTERNET_FLAG_RELOAD | INTERNET_FLAG_NO_CACHE_WRITE | INTERNET_FLAG_NO_UI | INTERNET_FLAG_KEEP_CONNECTION, 0);
			if (!request)
			{
				error = L"Sem conexão com o servidor de download.";
				Sleep(1500);
				continue;
			}
			DWORD status = 0, size = sizeof(status);
			HttpQueryInfoW(request, HTTP_QUERY_STATUS_CODE | HTTP_QUERY_FLAG_NUMBER, &status, &size, NULL);
			if (status != 200 && status != 206)
			{
				InternetCloseHandle(request);
				error = L"O servidor de download respondeu com erro " + std::to_wstring(status) + L".";
				Sleep(1500);
				continue;
			}
			if (status == 200 && have)   // o servidor mandou o arquivo inteiro de novo
			{
				EnterCriticalSection(&g_lock);
				g_received -= have;
				LeaveCriticalSection(&g_lock);
				have = 0;
			}
			HANDLE file = CreateFileW(partial.c_str(), GENERIC_WRITE, FILE_SHARE_READ, NULL, have ? OPEN_ALWAYS : CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
			if (file == INVALID_HANDLE_VALUE)
			{
				InternetCloseHandle(request);
				error = L"Não consegui gravar na pasta de download.";
				return false;
			}
			SetFilePointer(file, 0, NULL, FILE_END);
			std::vector<BYTE> buffer(256 * 1024);
			DWORD got = 0, written = 0;
			bool wrote = true;
			while (!g_cancel && InternetReadFile(request, buffer.data(), (DWORD)buffer.size(), &got) && got)
			{
				wrote = WriteFile(file, buffer.data(), got, &written, NULL) && written == got;
				if (!wrote) break;
				EnterCriticalSection(&g_lock);
				g_received += got;
				LeaveCriticalSection(&g_lock);
			}
			CloseHandle(file);
			InternetCloseHandle(request);
			if (!wrote)
			{
				error = L"O disco encheu ou não deixou gravar. Libere espaço e tente de novo.";
				return false;
			}
			if (g_cancel) return false;
		}
		if (FileSize(partial) == item.size)
		{
			MoveFileExW(partial.c_str(), target.c_str(), MOVEFILE_REPLACE_EXISTING);
			return true;
		}
		error = L"A conexão caiu no meio do download.";   // tenta de novo, continuando de onde parou
		Sleep(1500);
	}
	return false;
}

static DWORD WINAPI DownloadThread(LPVOID)
{
	HINTERNET session = InternetOpenW(L"MorphoDiagnostico/1.0", INTERNET_OPEN_TYPE_PRECONFIG, NULL, NULL, 0);
	std::vector<Item> items;
	if (!session || !ReadList(session, items))
	{
		if (session) InternetCloseHandle(session);
		SetStage(BROKEN, L"Não consegui falar com o site do Morpho. Confira a internet e tente de novo.");
		return 0;
	}
	if (items.empty())
	{
		InternetCloseHandle(session);
		SetStage(BROKEN, L"O instalador do Morpho ainda não foi publicado. Volte em breve: o aviso sai em morpho-cam.vercel.app.");
		return 0;
	}
	PWSTR downloads = NULL;
	std::wstring folder = g_folderOverride;
	if (folder.empty() && SUCCEEDED(SHGetKnownFolderPath(FOLDERID_Downloads, 0, NULL, &downloads)) && downloads) folder = downloads;
	if (downloads) CoTaskMemFree(downloads);
	if (folder.empty())
	{
		InternetCloseHandle(session);
		SetStage(BROKEN, L"Não encontrei a pasta Downloads.");
		return 0;
	}
	folder += L"\\Morpho";
	CreateDirectoryW(folder.c_str(), NULL);

	ULONGLONG total = 0, already = 0;
	for (const Item &item : items)
	{
		total += item.size;
		const ULONGLONG done = FileSize(folder + L"\\" + item.name);
		already += done == item.size ? done : (std::min)(item.size, FileSize(folder + L"\\" + item.name + L".parte"));
	}
	EnterCriticalSection(&g_lock);
	g_folder = folder;
	g_total = total;
	g_received = already;
	g_lastBytes = already;
	g_lastTick = GetTickCount();
	g_speed = 0;
	g_files = (int)items.size();
	g_file = 0;
	LeaveCriticalSection(&g_lock);
	SetStage(DOWNLOADING);

	std::wstring error;
	for (size_t i = 0; i < items.size() && !g_cancel; i++)
	{
		EnterCriticalSection(&g_lock);
		g_file = (int)i + 1;
		LeaveCriticalSection(&g_lock);
		const std::wstring target = folder + L"\\" + items[i].name;
		if (FileSize(target) == items[i].size) continue;   // ja baixado numa tentativa anterior
		if (!Fetch(session, items[i], target, error))
		{
			InternetCloseHandle(session);
			if (g_cancel) SetStage(READY);
			else SetStage(BROKEN, error.empty() ? L"O download não terminou." : error);
			return 0;
		}
	}
	InternetCloseHandle(session);
	if (g_cancel)
	{
		SetStage(READY);
		return 0;
	}

	// Confere a impressao digital de cada arquivo: download corrompido ou adulterado nao passa.
	EnterCriticalSection(&g_lock);
	g_received = 0;
	LeaveCriticalSection(&g_lock);
	SetStage(CHECKING);
	for (const Item &item : items)
	{
		const std::wstring target = folder + L"\\" + item.name;
		if (item.sha256.empty()) continue;
		const std::wstring digest = Sha256(target);
		if (g_cancel)
		{
			SetStage(READY);
			return 0;
		}
		if (_wcsicmp(digest.c_str(), item.sha256.c_str()) != 0)
		{
			DeleteFileW(target.c_str());
			SetStage(BROKEN, L"O arquivo " + item.name + L" chegou diferente do original e foi apagado. Clique para baixar de novo.");
			return 0;
		}
	}
	EnterCriticalSection(&g_lock);
	g_setup = folder + L"\\" + items[0].name;
	for (const Item &item : items)
		if (item.name.size() > 4 && _wcsicmp(item.name.c_str() + item.name.size() - 4, L".exe") == 0) g_setup = folder + L"\\" + item.name;
	LeaveCriticalSection(&g_lock);
	SetStage(DONE);
	return 0;
}

static void StartDownload()
{
	InterlockedExchange(&g_cancel, 0);
	EnterCriticalSection(&g_lock);
	g_error.clear();
	LeaveCriticalSection(&g_lock);
	SetStage(LISTING);
	HANDLE thread = CreateThread(NULL, 0, DownloadThread, NULL, 0, NULL);
	if (thread) CloseHandle(thread);
}

// ---- desenho ------------------------------------------------------------------------------
static REAL S(double value) { return (REAL)(value * g_scale); }

static void Rounded(GraphicsPath &path, RectF r, REAL radius)
{
	const REAL d = radius * 2;
	path.AddArc(r.X, r.Y, d, d, 180, 90);
	path.AddArc(r.X + r.Width - d, r.Y, d, d, 270, 90);
	path.AddArc(r.X + r.Width - d, r.Y + r.Height - d, d, d, 0, 90);
	path.AddArc(r.X, r.Y + r.Height - d, d, d, 90, 90);
	path.CloseFigure();
}

static void Fill(Graphics &g, RectF r, REAL radius, Color color)
{
	GraphicsPath path;
	Rounded(path, r, radius);
	SolidBrush brush(color);
	g.FillPath(&brush, &path);
}

static void Stroke(Graphics &g, RectF r, REAL radius, Color color)
{
	GraphicsPath path;
	Rounded(path, r, radius);
	Pen pen(color, 1);
	g.DrawPath(&pen, &path);
}

struct Type
{
	FontFamily family;
	Type() : family(L"Segoe UI") {}
	Font *Make(double size, bool bold = false) const { return new Font(&family, S(size), bold ? FontStyleBold : FontStyleRegular, UnitPixel); }
};

static REAL Write(Graphics &g, const std::wstring &text, double size, bool bold, Color color, RectF box,
				  StringAlignment horizontal = StringAlignmentNear, StringAlignment vertical = StringAlignmentNear, bool measureOnly = false)
{
	// Criado uma vez e nunca destruido: um objeto do GDI+ destruido no fim do processo,
	// depois do GdiplusShutdown, derruba o programa ao fechar.
	static Type *type = new Type();
	Font *font = type->Make(size, bold);
	StringFormat format;
	format.SetAlignment(horizontal);
	format.SetLineAlignment(vertical);
	format.SetTrimming(StringTrimmingEllipsisWord);
	RectF bounds;
	g.MeasureString(text.c_str(), -1, font, box, &format, &bounds);
	if (!measureOnly)
	{
		SolidBrush brush(color);
		g.DrawString(text.c_str(), -1, font, box, &format, &brush);
	}
	delete font;
	return bounds.Height;
}

static Color LevelColor(Level level) { return level == OK ? GO : level == WARN ? AMBER : STOP; }

static void Mark(Graphics &g, Level level, REAL x, REAL y, REAL size)
{
	SolidBrush brush(LevelColor(level));
	g.FillEllipse(&brush, x, y, size, size);
	Pen pen(Color(255, 14, 16, 20), S(2));
	pen.SetStartCap(LineCapRound);
	pen.SetEndCap(LineCapRound);
	pen.SetLineJoin(LineJoinRound);
	const REAL u = size / 20;
	if (level == OK)
	{
		PointF tick[3] = {PointF(x + 5.6f * u, y + 10.4f * u), PointF(x + 8.8f * u, y + 13.5f * u), PointF(x + 14.4f * u, y + 7.2f * u)};
		g.DrawLines(&pen, tick, 3);
	}
	else if (level == WARN)
	{
		g.DrawLine(&pen, x + 10 * u, y + 5.5f * u, x + 10 * u, y + 11 * u);
		g.DrawLine(&pen, x + 10 * u, y + 14.4f * u, x + 10 * u, y + 14.5f * u);
	}
	else
	{
		g.DrawLine(&pen, x + 6.5f * u, y + 6.5f * u, x + 13.5f * u, y + 13.5f * u);
		g.DrawLine(&pen, x + 13.5f * u, y + 6.5f * u, x + 6.5f * u, y + 13.5f * u);
	}
}

static void DrawButton(Graphics &g, RECT &where, RectF box, const std::wstring &label, bool primary, Button id, bool enabled = true)
{
	Color fill = primary ? (g_hover == id ? GO_HOVER : GO) : (g_hover == id ? Color(255, 46, 52, 66) : FIELD);
	if (!enabled) fill = FIELD;
	if (g_pressed == id && enabled) fill = Color(255, (BYTE)(fill.GetR() * 0.88), (BYTE)(fill.GetG() * 0.88), (BYTE)(fill.GetB() * 0.88));
	Fill(g, box, S(10), fill);
	if (!primary) Stroke(g, box, S(10), BORDER);
	Write(g, label, 14, primary, !enabled ? FAINT : primary ? Color(255, 6, 33, 15) : INK, box, StringAlignmentCenter, StringAlignmentCenter);
	SetRect(&where, (int)box.X, (int)box.Y, (int)(box.X + box.Width), (int)(box.Y + box.Height));
}

// Altura da lista de itens, para a janela nascer do tamanho do conteudo.
static REAL ListHeight(Graphics &g, REAL width)
{
	REAL height = S(14);
	for (const Check &check : g_report.checks)
		height += (std::max)(S(40), S(22) + Write(g, check.detail, 12.5, false, MUTED, RectF(0, 0, width - S(60), S(200)), StringAlignmentNear, StringAlignmentNear, true) + S(14));
	return height + S(6);
}

static const double HEADER = 92, FOOTER = 150, PAD = 28, LEFT = 268, GAP = 16;

static int ContentHeight(Graphics &g)
{
	const REAL list = ListHeight(g, S(WIDTH - PAD * 2 - LEFT - GAP));
	return (int)(S(HEADER) + (std::max)(list, S(330)) + S(FOOTER));
}

static void Paint(Graphics &g, int width, int height, double progress = -1)
{
	g.SetSmoothingMode(SmoothingModeAntiAlias);
	g.SetTextRenderingHint(TextRenderingHintClearTypeGridFit);
	g.Clear(WINDOW);
	const Report &r = g_report;

	// cabecalho
	if (g_icon)
	{
		HDC dc = g.GetHDC();
		DrawIconEx(dc, (int)S(PAD), (int)S(24), g_icon, (int)S(44), (int)S(44), 0, NULL, DI_NORMAL);
		g.ReleaseHDC(dc);
	}
	Write(g, L"Morpho", 21, true, INK, RectF(S(PAD + 58), S(22), S(400), S(30)));
	Write(g, L"Diagnóstico de compatibilidade", 13, false, MUTED, RectF(S(PAD + 58), S(49), S(500), S(22)));

	// nota
	const REAL top = S(HEADER), body = (REAL)height - S(HEADER) - S(FOOTER);
	const RectF left(S(PAD), top, S(LEFT), body);
	Fill(g, left, S(14), CARD);
	Stroke(g, left, S(14), BORDER);
	const REAL ring = S(164), cx = left.X + left.Width / 2, ringTop = left.Y + (body - S(250)) / 2;
	const Color tone = !r.compatible ? STOP : r.score >= 70 ? GO : r.score >= 50 ? ACCENT : AMBER;
	{
		Pen track(FIELD, S(11));
		g.DrawEllipse(&track, cx - ring / 2, ringTop, ring, ring);
		Pen arc(tone, S(11));
		arc.SetStartCap(LineCapRound);
		arc.SetEndCap(LineCapRound);
		if (r.compatible) g.DrawArc(&arc, cx - ring / 2, ringTop, ring, ring, -90.0f, (REAL)(360.0 * r.score / 100.0));
		else g.DrawEllipse(&arc, cx - ring / 2, ringTop, ring, ring);
	}
	if (r.compatible)
	{
		Write(g, std::to_wstring(r.score), 58, true, INK, RectF(cx - ring / 2, ringTop + S(34), ring, S(76)), StringAlignmentCenter, StringAlignmentCenter);
		Write(g, L"de 100", 12.5, false, MUTED, RectF(cx - ring / 2, ringTop + S(108), ring, S(22)), StringAlignmentCenter);
	}
	else
	{
		Pen cross(STOP, S(9));
		cross.SetStartCap(LineCapRound);
		cross.SetEndCap(LineCapRound);
		const REAL m = ring / 2, a = S(26);
		g.DrawLine(&cross, cx - a, ringTop + m - a, cx + a, ringTop + m + a);
		g.DrawLine(&cross, cx + a, ringTop + m - a, cx - a, ringTop + m + a);
	}
	Write(g, r.grade, 19, true, tone, RectF(left.X, ringTop + ring + S(20), left.Width, S(30)), StringAlignmentCenter);
	if (r.compatible)
	{
		const int fps = (int)(std::min)(60.0, std::floor(r.fps));
		Write(g, L"capacidade estimada: " + std::to_wstring(fps) + L" quadros/s", 12.5, false, MUTED,
			  RectF(left.X + S(12), ringTop + ring + S(52), left.Width - S(24), S(22)), StringAlignmentCenter);
	}

	// itens
	const RectF right(S(PAD + LEFT + GAP), top, (REAL)width - S(PAD * 2 + LEFT + GAP), body);
	Fill(g, right, S(14), CARD);
	Stroke(g, right, S(14), BORDER);
	REAL y = right.Y + S(14);
	for (const Check &check : r.checks)
	{
		const REAL textWidth = right.Width - S(60);
		const REAL detail = Write(g, check.detail, 12.5, false, MUTED, RectF(0, 0, textWidth, S(200)), StringAlignmentNear, StringAlignmentNear, true);
		Mark(g, check.level, right.X + S(16), y + S(3), S(20));
		Write(g, check.title, 13.5, true, INK, RectF(right.X + S(48), y, textWidth, S(22)));
		Write(g, check.detail, 12.5, false, check.level == OK ? MUTED : LevelColor(check.level), RectF(right.X + S(48), y + S(21), textWidth, detail + S(4)));
		y += (std::max)(S(40), S(22) + detail + S(14));
	}

	// rodape: veredito e botoes, ou o andamento do download
	const REAL foot = (REAL)height - S(FOOTER) + S(18);
	EnterCriticalSection(&g_lock);
	Stage stage = g_stage;
	ULONGLONG total = g_total, received = g_received;
	int file = g_file, files = g_files;
	const std::wstring error = g_error, folder = g_folder;
	const double speed = g_speed;
	LeaveCriticalSection(&g_lock);
	if (progress >= 0)   // tela de exemplo para capturas
	{
		stage = DOWNLOADING;
		total = 4294620694ull;
		received = (ULONGLONG)(total * progress);
		file = 2;
		files = 4;
	}
	SetRectEmpty(&g_primary);
	SetRectEmpty(&g_secondary);
	const REAL buttonWidth = S(214), buttonX = (REAL)width - S(PAD) - buttonWidth;
	if (stage == DOWNLOADING || stage == CHECKING || stage == LISTING)
	{
		const double fraction = total ? (std::min)(1.0, (double)received / (double)total) : 0;
		std::wstring title = stage == LISTING ? L"Preparando o download…" : stage == CHECKING ? L"Conferindo os arquivos…" : L"Baixando o Morpho";
		Write(g, title, 17, true, INK, RectF(S(PAD), foot, S(520), S(28)));
		std::wstring detail;
		if (stage == DOWNLOADING)
		{
			detail = Bytes(received) + L" de " + Bytes(total) + L"  ·  arquivo " + std::to_wstring(file) + L" de " + std::to_wstring(files);
			if (progress >= 0 || speed > 1024)
			{
				const double rate = progress >= 0 ? 11.5 * 1024 * 1024 : speed;
				const double seconds = (double)(total - received) / rate;
				wchar_t text[96];
				swprintf_s(text, L"  ·  %.1f MB/s  ·  faltam %d min", rate / (1024.0 * 1024.0), (int)std::ceil(seconds / 60.0));
				std::wstring more(text);
				std::replace(more.begin(), more.end(), L'.', L',');
				detail += more;
			}
		}
		else if (stage == CHECKING) detail = L"Comparando com a impressão digital publicada no site.";
		else detail = L"Buscando a lista de arquivos.";
		Write(g, detail, 13, false, MUTED, RectF(S(PAD), foot + S(28), (REAL)width - S(PAD * 2) - buttonWidth - S(20), S(22)));
		const RectF track(S(PAD), foot + S(62), (REAL)width - S(PAD * 2), S(8));
		Fill(g, track, S(4), FIELD);
		if (fraction > 0) Fill(g, RectF(track.X, track.Y, (std::max)(S(8), track.Width * (REAL)fraction), track.Height), S(4), ACCENT);
		Write(g, L"Vai para a pasta Downloads\\Morpho. Pode fechar e continuar depois: o download recomeça de onde parou.", 11.5, false, FAINT,
			  RectF(S(PAD), foot + S(82), (REAL)width - S(PAD * 2), S(20)));
		DrawButton(g, g_secondary, RectF(buttonX + S(74), foot - S(2), buttonWidth - S(74), S(36)), L"Cancelar", false, SECONDARY);
		return;
	}
	std::wstring verdict = r.verdict, advice = r.advice, primary, secondary = L"Copiar resultado";
	Color verdictColor = INK;
	if (stage == DONE)
	{
		verdict = L"Download concluído.";
		advice = L"Os arquivos estão em " + folder + L". Abra o instalador para continuar.";
		primary = L"Abrir o instalador";
		secondary = L"Abrir a pasta";
	}
	else if (stage == BROKEN)
	{
		verdict = L"Não deu para baixar agora.";
		advice = error;
		primary = L"Tentar de novo";
		verdictColor = AMBER;
	}
	else
		primary = r.compatible ? L"Baixar o Morpho" : L"Ver os requisitos";
	const REAL textWidth = (REAL)width - S(PAD * 2) - buttonWidth - S(24);
	Write(g, verdict, 17, true, verdictColor, RectF(S(PAD), foot, textWidth, S(28)));
	Write(g, advice, 13, false, MUTED, RectF(S(PAD), foot + S(28), textWidth, S(58)));
	DrawButton(g, g_primary, RectF(buttonX, foot, buttonWidth, S(44)), primary, r.compatible || stage == DONE, PRIMARY);
	DrawButton(g, g_secondary, RectF(buttonX, foot + S(52), buttonWidth, S(36)), secondary, false, SECONDARY);
	Write(g, L"A nota é uma estimativa: só uma placa (RTX 3060 de notebook) foi medida de verdade. Nada foi instalado nem alterado neste computador.",
		  11.5, false, FAINT, RectF(S(PAD), (REAL)height - S(34), (REAL)width - S(PAD * 2), S(20)));
}

// ---- janela -------------------------------------------------------------------------------
static void CopyResult()
{
	const std::wstring text = ToText(g_report);
	if (!OpenClipboard(g_window)) return;
	EmptyClipboard();
	HGLOBAL memory = GlobalAlloc(GMEM_MOVEABLE, (text.size() + 1) * sizeof(wchar_t));
	if (memory)
	{
		memcpy(GlobalLock(memory), text.c_str(), (text.size() + 1) * sizeof(wchar_t));
		GlobalUnlock(memory);
		SetClipboardData(CF_UNICODETEXT, memory);
	}
	CloseClipboard();
}

static void Click(Button button)
{
	EnterCriticalSection(&g_lock);
	const Stage stage = g_stage;
	const std::wstring setup = g_setup, folder = g_folder;
	LeaveCriticalSection(&g_lock);
	if (stage == DOWNLOADING || stage == CHECKING || stage == LISTING)
	{
		if (button == SECONDARY) InterlockedExchange(&g_cancel, 1);
		return;
	}
	if (button == PRIMARY)
	{
		if (stage == DONE) ShellExecuteW(g_window, L"open", setup.c_str(), NULL, folder.c_str(), SW_SHOWNORMAL);
		else if (!g_report.compatible) ShellExecuteW(g_window, L"open", SITE_URL L"/#requisitos", NULL, NULL, SW_SHOWNORMAL);
		else if ((double)g_report.diskFree / GB < NEED_DISK_GB &&
				 MessageBoxW(g_window, L"Há pouco espaço livre no disco: o download e a instalação precisam de 13 GB.\n\n"
									   L"Sem liberar espaço, a instalação deve falhar. Baixar mesmo assim?",
							 L"Morpho", MB_YESNO | MB_ICONWARNING | MB_DEFBUTTON2) != IDYES)
			return;
		else StartDownload();
	}
	else if (button == SECONDARY)
	{
		if (stage == DONE) ShellExecuteW(g_window, L"open", folder.c_str(), NULL, NULL, SW_SHOWNORMAL);
		else
		{
			CopyResult();
			MessageBoxW(g_window, L"O resultado foi copiado. É só colar onde quiser.", L"Morpho", MB_OK | MB_ICONINFORMATION);
		}
	}
}

static Button Hit(LPARAM point)
{
	const POINT p = {GET_X_LPARAM(point), GET_Y_LPARAM(point)};
	if (PtInRect(&g_primary, p)) return PRIMARY;
	if (PtInRect(&g_secondary, p)) return SECONDARY;
	return NONE;
}

static LRESULT CALLBACK WindowProc(HWND window, UINT message, WPARAM wParam, LPARAM lParam)
{
	switch (message)
	{
		case WM_PAINT:
		{
			PAINTSTRUCT paint;
			HDC dc = BeginPaint(window, &paint);
			RECT client;
			GetClientRect(window, &client);
			Bitmap buffer(client.right, client.bottom, PixelFormat24bppRGB);
			{
				Graphics g(&buffer);
				Paint(g, client.right, client.bottom);
			}
			Graphics screen(dc);
			screen.DrawImage(&buffer, 0, 0);
			EndPaint(window, &paint);
			return 0;
		}
		case WM_ERASEBKGND: return 1;
		case WM_MOUSEMOVE:
		{
			const Button now = Hit(lParam);
			if (now != g_hover)
			{
				g_hover = now;
				InvalidateRect(window, NULL, FALSE);
			}
			TRACKMOUSEEVENT track = {sizeof(track), TME_LEAVE, window, 0};
			TrackMouseEvent(&track);
			SetCursor(LoadCursor(NULL, now == NONE ? IDC_ARROW : IDC_HAND));
			return 0;
		}
		case WM_MOUSELEAVE:
			g_hover = g_pressed = NONE;
			InvalidateRect(window, NULL, FALSE);
			return 0;
		case WM_LBUTTONDOWN:
			g_pressed = Hit(lParam);
			InvalidateRect(window, NULL, FALSE);
			return 0;
		case WM_LBUTTONUP:
		{
			const Button released = Hit(lParam), pressed = g_pressed;
			g_pressed = NONE;
			InvalidateRect(window, NULL, FALSE);
			if (released != NONE && released == pressed) Click(released);
			return 0;
		}
		case WM_TIMER:
		{
			EnterCriticalSection(&g_lock);
			const bool busy = g_stage == DOWNLOADING || g_stage == CHECKING || g_stage == LISTING;
			if (g_stage == DOWNLOADING)
			{
				const DWORD now = GetTickCount();
				if (now - g_lastTick >= 900)
				{
					const double rate = (double)(g_received - g_lastBytes) * 1000.0 / (double)(now - g_lastTick);
					g_speed = g_speed <= 0 ? rate : g_speed * 0.7 + rate * 0.3;
					g_lastBytes = g_received;
					g_lastTick = now;
				}
			}
			LeaveCriticalSection(&g_lock);
			if (busy) InvalidateRect(window, NULL, FALSE);
			return 0;
		}
		case WM_APP:
			InvalidateRect(window, NULL, FALSE);
			if (!g_autoResult.empty())   // modo de teste: grava como o download terminou e fecha
			{
				EnterCriticalSection(&g_lock);
				const Stage stage = g_stage;
				const std::wstring result = stage == DONE ? L"ok " + g_setup : L"erro " + g_error;
				LeaveCriticalSection(&g_lock);
				if (stage == DONE || stage == BROKEN || stage == READY)
				{
					WriteFileText(g_autoResult, stage == READY ? L"cancelado" : result);
					DestroyWindow(window);
				}
			}
			return 0;
		case WM_CLOSE:
			InterlockedExchange(&g_cancel, 1);
			DestroyWindow(window);
			return 0;
		case WM_DESTROY:
			PostQuitMessage(0);
			return 0;
	}
	return DefWindowProcW(window, message, wParam, lParam);
}

static CLSID PngEncoder()
{
	CLSID id = {};
	UINT count = 0, size = 0;
	GetImageEncodersSize(&count, &size);
	std::vector<BYTE> buffer(size);
	ImageCodecInfo *codecs = (ImageCodecInfo *)buffer.data();
	if (size && GetImageEncoders(count, size, codecs) == Ok)
		for (UINT i = 0; i < count; i++)
			if (wcscmp(codecs[i].MimeType, L"image/png") == 0) id = codecs[i].Clsid;
	return id;
}

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE, PWSTR, int show)
{
	InitializeCriticalSection(&g_lock);
	GdiplusStartupInput startup;
	ULONG_PTR token;
	GdiplusStartup(&token, &startup, NULL);

	int count = 0;
	wchar_t **arguments = CommandLineToArgvW(GetCommandLineW(), &count);
	std::wstring json, shot, fake;
	double progress = -1, shotScale = 1.0;
	for (int i = 1; arguments && i < count; i++)
	{
		const std::wstring option = arguments[i];
		const wchar_t *value = i + 1 < count ? arguments[i + 1] : L"";
		if (option == L"--json") json = value, i++;
		else if (option == L"--shot") shot = value, i++;
		else if (option == L"--fake") fake = value, i++;
		else if (option == L"--progress") progress = _wtof(value), i++;
		else if (option == L"--scale") shotScale = _wtof(value), i++;
		else if (option == L"--manifest") g_manifest = value, i++;
		else if (option == L"--auto-download") g_autoResult = value, i++;
		else if (option == L"--folder") g_folderOverride = value, i++;
	}

	g_report = fake.empty() ? Measure() : Fake(fake);
	if (!json.empty())
	{
		WriteFileText(json, ToJson(g_report));
		return 0;
	}
	g_icon = (HICON)LoadImageW(instance, MAKEINTRESOURCEW(1), IMAGE_ICON, 256, 256, LR_DEFAULTCOLOR);

	if (!shot.empty())
	{
		g_scale = shotScale > 0 ? shotScale : 1.0;
		Bitmap probe(8, 8, PixelFormat24bppRGB);
		Graphics measure(&probe);
		const int width = (int)S(WIDTH), height = ContentHeight(measure);
		Bitmap image(width, height, PixelFormat24bppRGB);
		{
			Graphics g(&image);
			Paint(g, width, height, progress);
		}
		const CLSID png = PngEncoder();
		image.Save(shot.c_str(), &png, NULL);
		return 0;
	}

	WNDCLASSEXW windowClass = {sizeof(windowClass)};
	windowClass.lpfnWndProc = WindowProc;
	windowClass.hInstance = instance;
	windowClass.hCursor = LoadCursor(NULL, IDC_ARROW);
	windowClass.hIcon = LoadIconW(instance, MAKEINTRESOURCEW(1));
	windowClass.hIconSm = (HICON)LoadImageW(instance, MAKEINTRESOURCEW(1), IMAGE_ICON, 16, 16, LR_DEFAULTCOLOR);
	windowClass.lpszClassName = L"MorphoDiagnostico";
	RegisterClassExW(&windowClass);

	const DWORD style = WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX;
	g_window = CreateWindowExW(0, windowClass.lpszClassName, L"Morpho · Diagnóstico", style, CW_USEDEFAULT, CW_USEDEFAULT, 400, 300,
							   NULL, NULL, instance, NULL);
	if (!g_window) return 1;
	const UINT dpi = GetDpiForWindow(g_window);
	g_scale = dpi / 96.0;
	{
		Bitmap probe(8, 8, PixelFormat24bppRGB);
		Graphics measure(&probe);
		RECT frame = {0, 0, (int)S(WIDTH), ContentHeight(measure)};
		AdjustWindowRectExForDpi(&frame, style, FALSE, 0, dpi);
		// no centro do monitor em que a janela nasceu
		MONITORINFO monitor = {sizeof(monitor)};
		GetMonitorInfoW(MonitorFromWindow(g_window, MONITOR_DEFAULTTONEAREST), &monitor);
		const int w = frame.right - frame.left, h = frame.bottom - frame.top;
		SetWindowPos(g_window, NULL, monitor.rcWork.left + (monitor.rcWork.right - monitor.rcWork.left - w) / 2,
					 (std::max)(monitor.rcWork.top, monitor.rcWork.top + (monitor.rcWork.bottom - monitor.rcWork.top - h) / 2), w, h, SWP_NOZORDER);
	}
	BOOL dark = TRUE;
	DwmSetWindowAttribute(g_window, 20, &dark, sizeof(dark));   // barra de titulo escura
	SetTimer(g_window, 1, 250, NULL);
	ShowWindow(g_window, g_autoResult.empty() ? show : SW_SHOWMINNOACTIVE);
	UpdateWindow(g_window);
	if (!g_autoResult.empty()) StartDownload();

	MSG message;
	while (GetMessageW(&message, NULL, 0, 0) > 0)
	{
		TranslateMessage(&message);
		DispatchMessageW(&message);
	}
	GdiplusShutdown(token);
	return 0;
}
