;; Session-local helpers around SAL's exported Scheme API.
(begin
  (define (salpy/pp-string obj)
    (with-output-to-string (lambda () (sal/pp obj))))
  (define (salpy/pp-detailed-string obj)
    (with-output-to-string (lambda () (sal/pp-detailed obj))))
  (define (salpy/value-pp-string obj)
    (with-output-to-string (lambda () (sal-value/pp obj))))
  (define (salpy/class-name obj)
    (symbol->string (class-name-of (class-of obj))))
  (define (salpy/string obj)
    (cond
      ((string? obj) obj)
      ((symbol? obj) (symbol->string obj))
      (else (with-output-to-string (lambda () (display obj))))))
  (define (salpy/load-context-file! path)
    (sal-env/import-context-from-file! *sal-env* path)
    (sal/context (file-name->sal-context-name path)))
  (define (salpy/import-context! name)
    (sal-env/import-context! *sal-env* name)
    (sal/context name))
  (define (salpy/declaration-names decls)
    (map (lambda (decl) (symbol->string (sal-decl/name decl))) decls))
  (define (salpy/context-declaration-names ctx)
    (salpy/declaration-names (sal-context/declarations ctx)))
  (define (salpy/module-state-variable-names module)
    (salpy/declaration-names (sal-module/state-variables module)))
  (define (salpy/path-length-string path)
    (salpy/string (sal-path/length path)))

  ;; The LSAL parser expects output, not the legacy printer's new-output.
  (define-method (sal-ast->lsal-doc (ast <sal-new-output>) (info <pp-info++>) (depth <primitive>))
    (pp/list-style4 'output 2
      (apply pp/list-style6
        (map (lambda (id) (sal-ast->lsal-doc id info (+ depth 1)))
             (slot-value ast :identifiers)))
      (sal-ast->lsal-doc (slot-value ast :module) info (+ depth 1))))

  (define (salpy/lsal-source obj)
    (let ((info (copy-instance (make-default-pp-info++)
                  :max-depth 1048576 :max-num-lines 1048576
                  :simplify-qualified-names? #f)))
      (with-output-to-string
        (lambda () (pp/pretty (sal-ast->lsal-doc obj info 0) info)))))
  (define (salpy/parse-lsal-module text)
    (let ((old-reader (sal-env/string-reader *sal-env*)))
      (unwind-protect
        (begin
          (set-slot-value! *sal-env* :string-reader (make-lsal-string-reader *sal-env*))
          (sal/module text))
        (set-slot-value! *sal-env* :string-reader old-reader))))
  (define (salpy/checked-module module)
    (sal-module/update-interface! module)
    ;; The checker is not exported to SALenv. Parsing invokes it. LSAL preserves
    ;; qualification and avoids SAL's non-roundtripping observer printer.
    (salpy/parse-lsal-module (salpy/lsal-source module))
    module)
  (define (salpy/module-compose class left right)
    (let ((module (make-ast-instance class left :module1 left :module2 right)))
      (sal-module/update-interface! module)
      module))
  (define (salpy/module-organize class module names)
    (salpy/checked-module
      (make-ast-instance class module :module module
        :identifiers (map (lambda (name)
                            (make-ast-instance <sal-identifier> module
                              :name (string->symbol name))) names))))
  (define (salpy/module-rename module pairs)
    (let* ((new-decls
             (map (lambda (pair)
                    (let ((decl (sal-module/lookup-var module (string->symbol (car pair)))))
                      (unless decl
                        (sign-error "Unknown state variable in rename: ~a" (car pair)))
                      (copy-ast decl :id
                        (make-ast-instance <sal-identifier> module
                          :name (string->symbol (cadr pair)))))) pairs))
           (renames
             (map (lambda (pair decl)
                    (make-ast-instance <sal-rename> module
                      :from-name (make-ast-instance <sal-identifier> module
                                   :name (string->symbol (car pair)))
                      :to-expr (make-ast-instance <sal-name-expr> module :decl decl)))
                  pairs new-decls))
           (renamed (make-ast-instance <sal-renaming> module
                      :renames renames :module module)))
      (sal-module/update-interface! renamed)
      (salpy/checked-module
        (make-ast-instance <sal-with-module> module
          :new-state-vars new-decls :module renamed))))
  #unspecified)
