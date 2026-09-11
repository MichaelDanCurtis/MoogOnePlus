package main

// Presets as documents the editor can open and save.
//
// The instrument keeps its library in SQLite at /var/las-frontend and owns it
// absolutely. Nothing here touches that. This reads and writes `.m1p` files on
// the USB drive, which is the route the instrument already offers for import
// and export (`las-frontend --usb-path=/media/thumbdrive`), and which is
// reversible in the only way that matters: pulling the drive out.
//
// Everything below is confined to one directory, and a write replaces exactly
// one line of one file.

import (
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
)

type presetStore struct{ root string }

// resolve turns a client-supplied name into a path inside the store, or fails.
//
// The client is a web page and the name arrives in a query string, so this is
// the boundary where a traversal would happen. Cleaning is not enough on its
// own -- the check is that the resolved path is still under the root after
// symlinks are followed, because the drive is removable and its contents are
// not ours.
func (s *presetStore) resolve(name string) (string, error) {
	if name == "" {
		return "", fmt.Errorf("no preset named")
	}
	if !strings.HasSuffix(strings.ToLower(name), ".m1p") {
		return "", fmt.Errorf("%q is not a .m1p", name)
	}
	// Refuse traversal rather than neutralise it. filepath.Clean would quietly
	// turn "../elsewhere.m1p" into a file inside the root, which is safe but
	// writes somewhere other than the caller asked -- the wrong answer for a
	// save. An explicit refusal is the honest one.
	if filepath.IsAbs(name) {
		return "", fmt.Errorf("%q must be relative to the preset directory", name)
	}
	for _, part := range strings.Split(filepath.ToSlash(name), "/") {
		if part == ".." {
			return "", fmt.Errorf("%q leaves the preset directory", name)
		}
	}
	root, err := filepath.EvalSymlinks(s.root)
	if err != nil {
		return "", fmt.Errorf("preset directory %s: %w", s.root, err)
	}
	full := filepath.Join(root, filepath.Clean("/"+name))
	// EvalSymlinks fails on a file that does not exist yet; for a new file the
	// parent is what has to be inside.
	probe := full
	if _, err := os.Stat(probe); err != nil {
		probe = filepath.Dir(full)
	}
	real, err := filepath.EvalSymlinks(probe)
	if err != nil {
		return "", fmt.Errorf("%q: %w", name, err)
	}
	rel, err := filepath.Rel(root, real)
	if err != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
		return "", fmt.Errorf("%q is outside the preset directory", name)
	}
	return full, nil
}

type presetInfo struct {
	File     string `json:"file"`
	Name     string `json:"name"`
	Category string `json:"category,omitempty"`
	Timbres  []int  `json:"timbres"`
	Rows     int    `json:"rows"`
}

func (s *presetStore) list() ([]presetInfo, error) {
	var out []presetInfo
	err := filepath.Walk(s.root, func(p string, fi os.FileInfo, err error) error {
		if err != nil || fi.IsDir() || !strings.HasSuffix(strings.ToLower(p), ".m1p") {
			return nil //nolint:nilerr // an unreadable entry is skipped, not fatal
		}
		rel, err := filepath.Rel(s.root, p)
		if err != nil {
			return nil
		}
		b, err := os.ReadFile(p)
		if err != nil {
			return nil
		}
		pr := ParsePreset(string(b))
		info := presetInfo{File: rel, Name: pr.Meta("name"), Category: pr.Meta("category")}
		for _, t := range pr.Timbres() {
			info.Timbres = append(info.Timbres, t)
			if rows, err := pr.Matrix(t); err == nil {
				info.Rows += len(rows)
			}
		}
		if info.Name == "" {
			info.Name = strings.TrimSuffix(filepath.Base(rel), filepath.Ext(rel))
		}
		out = append(out, info)
		return nil
	})
	if err != nil {
		return nil, err
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Name < out[j].Name })
	return out, nil
}

func (s *presetStore) load(name string) (*Preset, error) {
	p, err := s.resolve(name)
	if err != nil {
		return nil, err
	}
	b, err := os.ReadFile(p)
	if err != nil {
		return nil, err
	}
	return ParsePreset(string(b)), nil
}

// save writes through a temporary file in the same directory and renames.
//
// A half-written preset on a drive somebody yanks is a destroyed patch, and
// rename is the only step that is atomic. The temp file is removed on any
// failure so a cancelled save leaves nothing behind.
func (s *presetStore) save(name string, pr *Preset) error {
	full, err := s.resolve(name)
	if err != nil {
		return err
	}
	tmp, err := os.CreateTemp(filepath.Dir(full), ".m1p-*")
	if err != nil {
		return err
	}
	defer os.Remove(tmp.Name())
	if _, err := tmp.WriteString(pr.String()); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Sync(); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	return os.Rename(tmp.Name(), full)
}

// -- handlers -----------------------------------------------------------------

func presetsHandler(s *presetStore) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		list, err := s.list()
		if err != nil {
			httpError(w, http.StatusInternalServerError, err)
			return
		}
		writeJSON(w, map[string]any{"root": s.root, "presets": list})
	}
}

type presetDoc struct {
	File    string            `json:"file"`
	Name    string            `json:"name"`
	Timbres map[string][]Slot `json:"timbres"`
}

func presetHandler(s *presetStore) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		file := r.URL.Query().Get("file")
		switch r.Method {
		case http.MethodGet:
			pr, err := s.load(file)
			if err != nil {
				httpError(w, http.StatusBadRequest, err)
				return
			}
			doc := presetDoc{File: file, Name: pr.Meta("name"), Timbres: map[string][]Slot{}}
			for _, t := range pr.Timbres() {
				rows, err := pr.Matrix(t)
				if err != nil {
					httpError(w, http.StatusInternalServerError, err)
					return
				}
				doc.Timbres[strconv.Itoa(t)] = rows
			}
			writeJSON(w, doc)

		case http.MethodPost:
			var body struct {
				Timbre int    `json:"timbre"`
				Slots  []Slot `json:"slots"`
			}
			if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
				httpError(w, http.StatusBadRequest, err)
				return
			}
			pr, err := s.load(file)
			if err != nil {
				httpError(w, http.StatusBadRequest, err)
				return
			}
			if err := pr.SetMatrix(body.Timbre, body.Slots); err != nil {
				httpError(w, http.StatusBadRequest, err)
				return
			}
			if err := s.save(file, pr); err != nil {
				httpError(w, http.StatusInternalServerError, err)
				return
			}
			writeJSON(w, map[string]any{"saved": file, "timbre": body.Timbre,
				"rows": len(body.Slots)})

		default:
			httpError(w, http.StatusMethodNotAllowed, fmt.Errorf("GET or POST"))
		}
	}
}

func writeJSON(w http.ResponseWriter, v any) {
	w.Header().Set("Content-Type", "application/json")
	enc := json.NewEncoder(w)
	enc.SetIndent("", "  ")
	_ = enc.Encode(v)
}

func httpError(w http.ResponseWriter, code int, err error) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(map[string]string{"error": err.Error()})
}
